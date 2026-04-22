"""Deduplication engine for finding and removing duplicate files.

This module provides a production-grade deduplication system that:
- Groups files by size before hashing (performance optimization)
- Uses MD5 hashing for content verification
- Supports multiple keeper selection strategies
- Handles hard links, copy markers, and UUID patterns
- Provides transaction logging for crash recovery
- Supports batch deletion for large file sets
"""

import logging
import os
import re
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from curate.core.hashing import file_hash, file_size, group_by_size, hash_files
from curate.core.progress import ProgressTracker
from curate.core.safety import DryRunContext
from curate.core.transaction import TransactionLog


# Default system directories to skip
DEFAULT_SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".DS_Store",
    "System Volume Information",
    "$RECYCLE.BIN",
    ".Trash-*",
}

# Default minimum file size (1 KB)
DEFAULT_MIN_SIZE = 1024

# Default batch size for batch deletion
DEFAULT_BATCH_SIZE = 500


@dataclass
class DedupResult:
    """Results from a deduplication operation."""

    total_files: int = 0
    duplicate_groups: int = 0
    files_to_delete: int = 0
    space_to_free: int = 0
    deleted_count: int = 0
    space_freed: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "total_files": self.total_files,
            "duplicate_groups": self.duplicate_groups,
            "files_to_delete": self.files_to_delete,
            "space_to_free": self.space_to_free,
            "deleted_count": self.deleted_count,
            "space_freed": self.space_freed,
            "error_count": len(self.errors),
            "errors": self.errors[:10],  # Limit to first 10 errors
        }


class DedupEngine:
    """
    Deduplication engine for finding and removing duplicate files.

    The engine uses a multi-stage process:
    1. Scan: Walk directory tree, collect file metadata
    2. Group: Group files by size (fast pre-filter)
    3. Hash: Compute MD5 hashes for same-size files
    4. Select: Choose which files to keep using strategy
    5. Execute: Delete duplicates (with transaction logging)

    Example:
        engine = DedupEngine(
            path=Path("/media/drive"),
            strategy="deepest",
            min_size=1024,
            dry_run=True
        )
        result = engine.run()
        print(f"Would free {result.space_to_free} bytes")
    """

    def __init__(
        self,
        path: Path,
        min_size: int = DEFAULT_MIN_SIZE,
        strategy: str = "deepest",
        include_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
        skip_dirs: Optional[Set[str]] = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        dry_run: bool = True,
        log_file: Optional[Path] = None,
    ) -> None:
        """
        Initialize deduplication engine.

        Args:
            path: Root path to scan for duplicates
            min_size: Minimum file size in bytes (default: 1024)
            strategy: Keeper selection strategy - "deepest", "newest", "largest"
            include_patterns: Glob patterns to include (e.g., ["*.jpg", "*.png"])
            exclude_patterns: Glob patterns to exclude (e.g., ["*.tmp"])
            skip_dirs: Directory names to skip (default: system dirs)
            batch_size: Batch size for batch deletion mode
            dry_run: If True, scan but don't delete (default: True)
            log_file: Optional path to transaction log file
        """
        self.path = Path(path)
        self.min_size = min_size
        self.strategy = strategy
        self.include_patterns = include_patterns
        self.exclude_patterns = exclude_patterns
        self.skip_dirs = skip_dirs if skip_dirs is not None else DEFAULT_SKIP_DIRS
        self.batch_size = batch_size
        self.dry_run = dry_run
        self.log_file = log_file

        # Setup logging
        self.logger = logging.getLogger(__name__)

        # Transaction log
        self.txn_log: Optional[TransactionLog] = None

    def scan(self) -> List[Tuple[Path, int]]:
        """
        Scan directory tree for files matching criteria.

        Returns:
            List of (path, size) tuples for files that match filters
        """
        files = []
        total_size = 0

        self.logger.info(f"Scanning {self.path} for files (min size: {self._format_size(self.min_size)})...")

        for root, dirs, filenames in os.walk(self.path):
            root_path = Path(root)

            # Filter out excluded directories
            dirs[:] = [d for d in dirs if not self._should_skip_dir(root_path / d)]

            for filename in filenames:
                file_path = root_path / filename

                try:
                    size = file_path.stat().st_size

                    # Size filter
                    if size < self.min_size:
                        continue

                    # Pattern filters
                    if not self._should_include_file(file_path):
                        continue

                    files.append((file_path, size))
                    total_size += size

                except (OSError, PermissionError) as e:
                    self.logger.warning(f"Cannot access {file_path}: {e}")
                    continue

        self.logger.info(f"Found {len(files):,} files ({self._format_size(total_size)} total)")

        return files

    def select_keepers(
        self, groups: Dict[Tuple[str, int], List[Tuple[Path, int]]]
    ) -> Dict[str, List[Tuple[Path, int]]]:
        """
        Select which files to keep from each duplicate group.

        Args:
            groups: Dictionary mapping (hash, size) to list of (path, size) tuples

        Returns:
            Dictionary mapping hash to list of (keeper_path, size) and duplicates to delete
        """
        selected = {}

        for (md5_hash, size), files in groups.items():
            if len(files) < 2:
                continue

            keeper_path, keeper_size = self._select_keeper(files)
            duplicates = [f for f in files if f[0] != keeper_path]

            selected[md5_hash] = {
                "keeper": (keeper_path, keeper_size),
                "duplicates": duplicates,
                "size": size,
            }

        return selected

    def execute(
        self, groups: Dict[str, List[Tuple[Path, int]]], batch_mode: bool = False
    ) -> DedupResult:
        """
        Execute deletion of duplicate files.

        Args:
            groups: Dictionary from select_keepers() mapping hash to keeper/duplicates
            batch_mode: If True, use batch deletion for performance

        Returns:
            DedupResult with statistics
        """
        result = DedupResult()

        # Setup transaction log
        if self.log_file:
            self.txn_log = TransactionLog(self.log_file)
            self.logger.info(f"Transaction log: {self.log_file}")

        # Count files to delete and calculate space
        for hash_val, group in groups.items():
            result.duplicate_groups += 1
            result.files_to_delete += len(group["duplicates"])
            result.space_to_free += group["size"] * len(group["duplicates"])

        if batch_mode:
            result = self._execute_batch(groups, result)
        else:
            result = self._execute_standard(groups, result)

        return result

    def run(self, batch_mode: bool = False) -> DedupResult:
        """
        Run full deduplication pipeline.

        Args:
            batch_mode: If True, use batch deletion mode

        Returns:
            DedupResult with statistics
        """
        start_time = time.time()

        # Phase 1: Scan
        files = self.scan()
        result = DedupResult(total_files=len(files))

        if not files:
            return result

        # Phase 2: Group by size
        self.logger.info("Grouping by size...")
        size_groups = group_by_size(files)

        total_groups = len(size_groups)
        dup_groups = sum(1 for files in size_groups.values() if len(files) >= 2)

        self.logger.info(f"  {len(files):,} files → {total_groups:,} size groups")
        self.logger.info(f"  {dup_groups:,} groups with potential duplicates")

        # Phase 3: Hash files
        self.logger.info("Hashing files...")
        hash_groups, failed_files = hash_files(size_groups)

        if failed_files:
            self.logger.info(f"Excluded {len(failed_files)} files that failed to hash")

        # Phase 4: Select keepers
        selected = self.select_keepers(hash_groups)

        # Phase 5: Execute
        result.total_files = len(files)
        result = self.execute(selected, batch_mode=batch_mode)
        result.total_files = len(files)  # Preserve total_files after execute

        # Log timing
        elapsed = time.time() - start_time
        self.logger.info(f"Time elapsed: {elapsed//60:.0f}m {elapsed%60:.0f}s")

        return result

    # -----------------------------------------------------------------------
    # Private methods
    # -----------------------------------------------------------------------

    def _should_skip_dir(self, dir_path: Path) -> bool:
        """Check if directory should be skipped."""
        # Check against skip dirs
        for parent in dir_path.parts:
            if parent in self.skip_dirs:
                return True

        # Check against skip patterns (e.g., .Trash-*)
        for pattern in self.skip_dirs:
            if "*" in pattern:
                import fnmatch

                if fnmatch.fnmatch(dir_path.name, pattern):
                    return True

        return False

    def _should_include_file(self, file_path: Path) -> bool:
        """Check if file should be included based on filters."""
        # Skip symlinks
        if file_path.is_symlink():
            return False

        # Skip zero-byte files
        if file_path.stat().st_size == 0:
            return False

        # Skip hidden files
        if file_path.name.startswith("."):
            return False

        # Extension filters
        if self.include_patterns:
            import fnmatch

            if not any(fnmatch.fnmatch(file_path.name, p) for p in self.include_patterns):
                return False

        if self.exclude_patterns:
            import fnmatch

            if any(fnmatch.fnmatch(file_path.name, p) for p in self.exclude_patterns):
                return False

        return True

    def _select_keeper(self, files: List[Tuple[Path, int]]) -> Tuple[Path, int]:
        """Select the best file to keep from a duplicate group."""
        if self.strategy == "newest":
            return self._select_keeper_newest(files)
        elif self.strategy == "largest":
            return self._select_keeper_largest(files)
        else:  # default: deepest
            return self._select_keeper_deepest(files)

    def _select_keeper_deepest(self, files: List[Tuple[Path, int]]) -> Tuple[Path, int]:
        """Select keeper with deepest path (fewer nested dirs = better)."""
        scored = [(self._score_keeper_path(path), path, size) for path, size in files]
        scored.sort(key=lambda x: (x[0], len(str(x[1]))))
        return scored[0][1], scored[0][2]

    def _select_keeper_newest(self, files: List[Tuple[Path, int]]) -> Tuple[Path, int]:
        """Select keeper with newest modification time."""
        newest = max(files, key=lambda f: f[0].stat().st_mtime)
        return newest

    def _select_keeper_largest(self, files: List[Tuple[Path, int]]) -> Tuple[Path, int]:
        """Select keeper with largest size (all same in dedup, but for interface consistency)."""
        largest = max(files, key=lambda f: f[1])
        return largest

    def _score_keeper_path(self, file_path: Path) -> Tuple[int, int, int, int]:
        """
        Score a path for keeper selection (lower is better).

        Returns tuple: (depth, has_copy_marker, has_uuid, has_parens)
        """
        # Priority 1: Path depth (fewer nested dirs = better)
        depth = len(file_path.parts)

        # Priority 2: Check for copy markers
        name_lower = file_path.name.lower()
        has_copy_marker = 0 if self._has_copy_marker(name_lower) else 1

        # Priority 3: Check for UUID pattern
        has_uuid = 0 if self._has_uuid_pattern(str(file_path)) else 1

        # Priority 4: Check for (1), (2), etc.
        has_parens = 0 if re.search(r"\(\d+\)", file_path.name) else 1

        return (depth, has_copy_marker, has_uuid, has_parens)

    def _has_copy_marker(self, filename: str) -> bool:
        """Check if filename contains copy marker."""
        copy_patterns = [
            "copy of ",
            " - copy",
            " - copie",
            " - copy (",
            "(1)",
            "(2)",
            "(3)",
        ]
        return any(pattern in filename for pattern in copy_patterns)

    def _has_uuid_pattern(self, path_str: str) -> bool:
        """Check if path contains UUID pattern."""
        uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        return re.search(uuid_pattern, path_str.lower()) is not None

    def _execute_standard(
        self, groups: Dict[str, List[Tuple[Path, int]]], result: DedupResult
    ) -> DedupResult:
        """Execute standard (one-by-one) deletion."""
        self.logger.info(f"\nProcessing {len(groups)} duplicate groups...")

        for idx, (hash_val, group) in enumerate(groups.items(), 1):
            keeper_path, keeper_size = group["keeper"]
            duplicates = group["duplicates"]

            self.logger.info(f"\n[{idx}/{len(groups)}] Group: {len(duplicates)+1} files")
            self.logger.info(f"  Keeper: {keeper_path}")

            # Pre-flight check: verify keeper is accessible
            if not self._verify_keeper(keeper_path, keeper_size):
                result.errors.append(f"Keeper verification failed: {keeper_path}")
                continue

            # Delete duplicates
            for dup_path, dup_size in duplicates:
                self.logger.info(f"  Deleting: {dup_path}")

                if not self.dry_run:
                    # Log transaction
                    if self.txn_log:
                        entry_idx = self.txn_log.log_operation(
                            op_type="delete",
                            source=dup_path,
                            hash_val=hash_val,
                            expected_size=dup_size,
                        )

                    # Delete file
                    success = self._delete_file(dup_path, dup_size)

                    if success:
                        result.deleted_count += 1
                        result.space_freed += dup_size

                        # Mark transaction complete
                        if self.txn_log:
                            self.txn_log.mark_completed(entry_idx)
                    else:
                        result.errors.append(f"Failed to delete: {dup_path}")
                        if self.txn_log:
                            self.txn_log.mark_failed(entry_idx)
                else:
                    # Dry run - just count
                    result.deleted_count += 1
                    result.space_freed += dup_size

            # Post-deletion verification
            if not self.dry_run and result.deleted_count > 0:
                self._verify_keeper_post_delete(keeper_path, keeper_size)

        return result

    def _execute_batch(
        self, groups: Dict[str, List[Tuple[Path, int]]], result: DedupResult
    ) -> DedupResult:
        """Execute batch deletion for performance."""
        batch_file = Path(f"/tmp/curate_dedup_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")

        self.logger.info(f"\nCollecting duplicates for batch deletion...")

        # Collect all duplicates to delete
        dupes_to_delete = []
        keeper_list = []

        for hash_val, group in groups.items():
            keeper_path, keeper_size = group["keeper"]
            keeper_list.append((keeper_path, keeper_size, hash_val))

            for dup_path, dup_size in group["duplicates"]:
                dupes_to_delete.append(dup_path)

        # Write batch file
        if not self.dry_run:
            with open(batch_file, "w") as f:
                for dupe_path in dupes_to_delete:
                    f.write(f"{dupe_path}\n")

            self.logger.info(f"  Batch file: {batch_file} ({len(dupes_to_delete):,} files)")

        # Delete in batches
        if not self.dry_run:
            for i in range(0, len(dupes_to_delete), self.batch_size):
                chunk = dupes_to_delete[i : i + self.batch_size]
                chunk_num = i // self.batch_size + 1
                total_chunks = (len(dupes_to_delete) + self.batch_size - 1) // self.batch_size

                self.logger.info(f"  Processing chunk {chunk_num}/{total_chunks}...")

                try:
                    subprocess.run(
                        ["rm", "-f"] + [str(p) for p in chunk],
                        capture_output=True,
                        timeout=120,
                    )

                    result.deleted_count += len(chunk)
                    result.space_freed += sum(f[1] for f in groups.values() for f in f["duplicates"])
                except (subprocess.TimeoutExpired, Exception) as e:
                    self.logger.error(f"  Error deleting chunk: {e}")

            # Verify keepers
            self.logger.info("\nVerifying keepers...")
            for keeper_path, keeper_size, _ in keeper_list:
                if not keeper_path.exists():
                    result.errors.append(f"Keeper missing: {keeper_path}")
                elif keeper_path.stat().st_size != keeper_size:
                    result.errors.append(f"Keeper size changed: {keeper_path}")

            # Cleanup batch file
            if batch_file.exists():
                batch_file.unlink()
        else:
            # Dry run - just count
            result.deleted_count = len(dupes_to_delete)
            result.space_freed = result.space_to_free

        return result

    def _verify_keeper(self, keeper_path: Path, keeper_size: int) -> bool:
        """Verify keeper file is accessible and correct size."""
        try:
            if not keeper_path.exists():
                self.logger.error(f"Keeper does not exist: {keeper_path}")
                return False

            current_size = keeper_path.stat().st_size
            if current_size != keeper_size:
                self.logger.error(f"Keeper size mismatch: {keeper_path}")
                return False

            return True

        except OSError as e:
            self.logger.error(f"Cannot verify keeper {keeper_path}: {e}")
            return False

    def _verify_keeper_post_delete(self, keeper_path: Path, keeper_size: int) -> None:
        """Verify keeper after deletion (data integrity check)."""
        try:
            if not keeper_path.exists():
                self.logger.critical(f"CRITICAL: Keeper disappeared after deletion: {keeper_path}")
            elif keeper_path.stat().st_size != keeper_size:
                self.logger.critical(f"CRITICAL: Keeper size changed after deletion: {keeper_path}")
        except OSError as e:
            self.logger.critical(f"CRITICAL: Cannot verify keeper after deletion: {e}")

    def _delete_file(self, file_path: Path, expected_size: int) -> bool:
        """Delete a single file with verification."""
        # Verify file exists
        if not file_path.exists():
            self.logger.warning(f"File no longer exists: {file_path}")
            return True

        # Verify size unchanged
        try:
            current_size = file_path.stat().st_size
            if current_size != expected_size:
                self.logger.warning(f"File size changed, skipping: {file_path}")
                return False
        except OSError as e:
            self.logger.warning(f"Cannot stat file: {file_path}")
            return False

        # Delete file
        try:
            file_path.unlink()
            return True
        except OSError as e:
            self.logger.warning(f"Failed to delete {file_path}: {e}")
            return False

    @staticmethod
    def _format_size(bytes_size: int) -> str:
        """Format byte size to human-readable string."""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.1f} PB"
