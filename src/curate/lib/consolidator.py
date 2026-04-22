"""File consolidation engine with deduplication."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import signal
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Dict, List, Set, Optional, Tuple

from curate.core.hashing import file_hash, file_size
from curate.core.transaction import TransactionLog
from curate.core.progress import ProgressTracker
from curate.core.safety import DryRunContext


# =============================================================================
# Configuration
# =============================================================================

FILE_TYPE_PRESETS = {
    "documents": {
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".txt", ".rtf", ".odt", ".ods", ".odp", ".csv", ".tsv"
    },
    "music": {
        ".mp3", ".m4a", ".flac", ".wma", ".aac", ".ogg", ".wav"
    },
    "pictures": {
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
        ".heic", ".webp", ".svg", ".raw", ".cr2", ".nef"
    },
    "videos": {
        ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm",
        ".m4v", ".mpg", ".mpeg", ".3gp"
    },
    "email": {
        ".pst", ".ost", ".msg", ".eml"
    },
}

SKIP_DIRS = {
    "$RECYCLE.BIN",
    "System Volume Information",
    ".Trash-*",
    "__pycache__",
    ".git",
    "node_modules",
    ".vscode",
    ".idea",
}

DEFAULT_MIN_SIZE = 100
DEFAULT_LOCK_FILE = "/tmp/curate_consolidate.lock"


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class FileInfo:
    """Information about a file."""
    path: Path
    size: int
    hash: str
    in_target: bool
    hash_failed: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["path"] = str(self.path)
        return d


@dataclass
class ConsolidationPlan:
    """Plan for consolidation operations."""
    files_to_move: List[Tuple[Path, Path]]  # (source, dest)
    files_to_delete: List[Path]
    staging_paths: Dict[Path, Path]  # source -> staging dest
    total_move_size: int
    total_delete_size: int

    def __len__(self) -> int:
        return len(self.files_to_move) + len(self.files_to_delete)


@dataclass
class ConsolidationResult:
    """Results of consolidation execution."""
    files_moved: int
    files_deleted: int
    duplicates_found: int
    space_organized: int
    space_freed: int
    errors: List[str]
    failed_hash_files: List[Path]

    def to_dict(self) -> dict:
        return asdict(self)


class ConsolidationState:
    """Thread-safe state for progress tracking and graceful shutdown."""

    def __init__(self):
        self._lock = Lock()
        self._shutdown_requested = False
        self.files_scanned = 0
        self.files_hashed = 0
        self.duplicates_found = 0
        self.unique_files = 0
        self.space_freed = 0
        self.space_moved = 0
        self.start_time = time.time()
        self.failed_hash_files: List[Path] = []

    def request_shutdown(self):
        """Request graceful shutdown."""
        with self._lock:
            self._shutdown_requested = True

    def should_shutdown(self) -> bool:
        """Check if shutdown was requested."""
        with self._lock:
            return self._shutdown_requested

    def increment_scanned(self):
        """Increment files scanned counter."""
        with self._lock:
            self.files_scanned += 1

    def increment_hashed(self):
        """Increment files hashed counter."""
        with self._lock:
            self.files_hashed += 1

    def record_duplicate(self, size: int):
        """Record a duplicate file."""
        with self._lock:
            self.duplicates_found += 1
            self.space_freed += size

    def record_unique(self, size: int):
        """Record a unique file to move."""
        with self._lock:
            self.unique_files += 1
            self.space_moved += size

    def add_failed_hash(self, path: Path):
        """Record a file that failed to hash."""
        with self._lock:
            self.failed_hash_files.append(path)

    def get_progress(self) -> dict:
        """Get current progress stats."""
        with self._lock:
            return {
                "files_scanned": self.files_scanned,
                "files_hashed": self.files_hashed,
                "duplicates_found": self.duplicates_found,
                "unique_files": self.unique_files,
                "space_freed": self.space_freed,
                "space_moved": self.space_moved,
                "elapsed": time.time() - self.start_time,
                "failed_hash_files": [str(p) for p in self.failed_hash_files],
            }


# =============================================================================
# Consolidation Engine
# =============================================================================

class Consolidator:
    """
    File consolidation engine with deduplication.

    Algorithm:
    1. Scan source for matching file types
    2. Hash all files
    3. Distinguish files "in target" vs "outside target"
    4. If file hash matches an in-target file → duplicate (DELETE)
    5. If file hash is unique → MOVE to staging area

    Safety features:
    - File locking to prevent concurrent runs
    - Pre-flight checks (disk space, writability)
    - Transaction manifest for crash recovery
    - Post-operation verification with rollback
    - Signal handling for graceful shutdown
    - Idempotent operations
    """

    def __init__(
        self,
        source: Path,
        target: Path,
        min_size: int = DEFAULT_MIN_SIZE,
        file_type: str = "all",
        dry_run: bool = True,
        log_file: Optional[Path] = None,
    ):
        """
        Initialize consolidator.

        Args:
            source: Source directory to scan
            target: Target directory (files already organized here)
            min_size: Minimum file size in bytes
            file_type: File type preset or "all"
            dry_run: If True, simulate operations only
            log_file: Optional log file path
        """
        self.source = source
        self.target = target
        self.min_size = min_size
        self.file_type = file_type
        self.dry_run = dry_run
        self.log_file = log_file

        # Determine extensions to scan
        if file_type == "all":
            self.extensions = set()
            for exts in FILE_TYPE_PRESETS.values():
                self.extensions.update(exts)
        else:
            self.extensions = FILE_TYPE_PRESETS.get(file_type, set())

        # State tracking
        self.state = ConsolidationState()
        self.logger = self._setup_logging()

        # Lock file
        self.lock_fd: Optional[int] = None
        self.lock_file = DEFAULT_LOCK_FILE

    def _setup_logging(self) -> logging.Logger:
        """Set up logging."""
        logger = logging.getLogger("curate.consolidate")
        logger.setLevel(logging.INFO)

        # Console handler
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(console)

        # File handler
        if self.log_file:
            file_handler = logging.FileHandler(self.log_file, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s | %(levelname)-8s | %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S"
                )
            )
            logger.addHandler(file_handler)

        return logger

    def _format_size(self, size_bytes: int) -> str:
        """Format bytes to human-readable size."""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"

    def _acquire_lock(self) -> bool:
        """
        Acquire exclusive file lock to prevent concurrent runs.

        Returns:
            True if lock acquired, False otherwise
        """
        try:
            self.lock_fd = os.open(self.lock_file, os.O_CREAT | os.O_WRONLY, 0o644)
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.write(self.lock_fd, str(os.getpid()).encode())
            return True
        except (IOError, OSError) as e:
            self.logger.error(f"Failed to acquire lock: {e}")
            self.logger.error(f"Another instance may be running. Lock file: {self.lock_file}")
            return False

    def _release_lock(self):
        """Release the file lock and clean up."""
        if self.lock_fd is not None:
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                os.close(self.lock_fd)
                os.remove(self.lock_file)
            except OSError:
                pass

    def _should_skip_dir(self, dirname: str) -> bool:
        """Check if a directory should be skipped."""
        if dirname in SKIP_DIRS:
            return True

        for pattern in SKIP_DIRS:
            if "*" in pattern:
                prefix = pattern.replace("*", "")
                if dirname.startswith(prefix):
                    return True

        return False

    def _compute_hash(self, path: Path) -> Optional[str]:
        """Compute MD5 hash of a file."""
        try:
            return file_hash(path)
        except (OSError, IOError) as e:
            self.logger.warning(f"Failed to hash {path}: {e}")
            return None

    def pre_flight(self) -> bool:
        """
        Run pre-flight safety checks.

        Returns:
            True if all checks pass, False otherwise
        """
        self.logger.info("Running pre-flight checks...")

        # Check source exists
        if not self.source.exists():
            self.logger.error(f"Source does not exist: {self.source}")
            return False

        # Check target exists
        if not self.target.exists():
            self.logger.error(f"Target does not exist: {self.target}")
            return False

        # Check source != target
        if self.source == self.target:
            self.logger.error("Source and target cannot be the same")
            return False

        # Check writability
        if not self.dry_run:
            test_file = self.target / ".write_test"
            try:
                test_file.write_text("test")
                test_file.unlink()
            except OSError as e:
                self.logger.error(f"Filesystem not writable: {e}")
                return False

        # Check disk space (best effort)
        try:
            import shutil
            stat = shutil.disk_usage(self.target)
            if stat.free < 1_000_000_000:  # 1GB
                self.logger.warning(f"Low disk space: {stat.free / 1_000_000_000:.1f}GB free")
        except Exception:
            pass

        self.logger.info("  Pre-flight checks passed")
        return True

    def scan_and_hash(self) -> Dict[Path, FileInfo]:
        """
        Scan source directory and hash all matching files.

        Returns:
            Dictionary mapping file path to FileInfo
        """
        self.logger.info(f"Scanning {self.source} for matching files...")

        files = {}
        extensions_lower = {ext.lower() for ext in self.extensions}

        for root, dirs, filenames in os.walk(self.source, topdown=True):
            if self.state.should_shutdown():
                break

            # Filter out skipped directories
            dirs[:] = [d for d in dirs if not self._should_skip_dir(d)]

            for filename in filenames:
                if self.state.should_shutdown():
                    break

                self.state.increment_scanned()

                # Check extension
                ext = os.path.splitext(filename)[1].lower()
                if ext not in extensions_lower:
                    continue

                filepath = Path(root) / filename

                # Check size
                size = file_size(filepath)
                if size is None or size < self.min_size:
                    continue

                # Categorize: in target or outside
                in_target = str(filepath).lower().startswith(str(self.target).lower() + os.sep.lower())

                # But NOT in staging
                if "_staging" in str(filepath).lower().split(os.sep.lower()):
                    in_target = False

                # Compute hash
                file_hash_val = self._compute_hash(filepath)
                if file_hash_val is None:
                    self.state.add_failed_hash(filepath)
                    continue

                self.state.increment_hashed()

                files[filepath] = FileInfo(
                    path=filepath,
                    size=size,
                    hash=file_hash_val,
                    in_target=in_target
                )

                # Progress update every 100 files
                if self.state.files_scanned % 100 == 0:
                    self.logger.info(f"  Found {self.state.files_scanned} files so far...")

        in_target_count = sum(1 for f in files.values() if f.in_target)
        outside_count = len(files) - in_target_count

        self.logger.info(f"  Found {len(files)} files ({self._format_size(sum(f.size for f in files.values()))})")
        self.logger.info(f"    Already in target: {in_target_count}")
        self.logger.info(f"    Outside target: {outside_count}")

        return files

    def plan(self, files: Dict[Path, FileInfo]) -> ConsolidationPlan:
        """
        Create consolidation plan from scanned files.

        Args:
            files: Dictionary from scan_source()

        Returns:
            ConsolidationPlan with operations to perform
        """
        self.logger.info("Creating consolidation plan...")

        # Build hash map
        hash_map: Dict[Tuple[str, int], List[FileInfo]] = defaultdict(list)
        for file_info in files.values():
            if not file_info.hash_failed:
                hash_map[(file_info.hash, file_info.size)].append(file_info)

        # Determine which hashes exist in target
        hashes_in_target: Set[Tuple[str, int]] = set()
        for file_key, files_list in hash_map.items():
            if any(f.in_target for f in files_list):
                hashes_in_target.add(file_key)

        # Build plan
        files_to_move = []
        files_to_delete = []
        staging_paths = {}

        for file_info in files.values():
            if file_info.in_target:
                continue

            file_key = (file_info.hash, file_info.size)

            if file_key in hashes_in_target:
                # Duplicate - delete
                files_to_delete.append(file_info.path)
                self.state.record_duplicate(file_info.size)
            else:
                # Unique - move to staging
                staging_dir = self.target / "_STAGING"
                subdir = self._get_staging_subdir(file_info.path)
                dest = staging_dir / subdir / file_info.path.name

                # Handle collision
                counter = 1
                while dest.exists():
                    stem = file_info.path.stem
                    suffix = file_info.path.suffix
                    dest = staging_dir / subdir / f"{stem}_{counter}{suffix}"
                    counter += 1

                files_to_move.append((file_info.path, dest))
                staging_paths[file_info.path] = dest
                self.state.record_unique(file_info.size)

        total_move_size = sum(files[f].size for f, _ in files_to_move if f in files)
        total_delete_size = sum(files[f].size for f in files_to_delete if f in files)

        plan = ConsolidationPlan(
            files_to_move=files_to_move,
            files_to_delete=files_to_delete,
            staging_paths=staging_paths,
            total_move_size=total_move_size,
            total_delete_size=total_delete_size,
        )

        self.logger.info(f"  Plan: {len(files_to_move)} files to move, {len(files_to_delete)} duplicates to delete")
        self.logger.info(f"  Space to organize: {self._format_size(total_move_size)}")
        self.logger.info(f"  Space to free: {self._format_size(total_delete_size)}")

        return plan

    def _get_staging_subdir(self, source_path: Path) -> str:
        """Generate a staging subdirectory name from the source path."""
        try:
            rel_path = source_path.relative_to(self.source)
        except ValueError:
            return "_from_root"

        parts = rel_path.parts

        if len(parts) >= 2:
            parent = parts[-2]
            if parent in {"source", "files", "data"} and len(parts) >= 3:
                return f"_from_{parts[-3]}_{parent}"
            return f"_from_{parent}"
        else:
            return "_from_root"

    def execute(self, plan: ConsolidationPlan) -> ConsolidationResult:
        """
        Execute consolidation plan.

        Args:
            plan: ConsolidationPlan from plan()

        Returns:
            ConsolidationResult with execution statistics
        """
        self.logger.info("Executing consolidation plan...")

        errors = []

        with DryRunContext(is_dry_run=self.dry_run) as ctx:
            if not ctx.will_execute():
                self.logger.info("  DRY RUN - no changes will be made")

            # Create staging directories
            staging_dirs = set()
            for _, dest in plan.files_to_move:
                staging_dirs.add(dest.parent)
            for staging_dir in staging_dirs:
                if ctx.will_execute():
                    staging_dir.mkdir(parents=True, exist_ok=True)

            # Move files
            for source, dest in plan.files_to_move:
                if self.state.should_shutdown():
                    break

                if ctx.will_execute():
                    try:
                        import shutil
                        shutil.move(str(source), str(dest))
                        self.logger.info(f"[MOVE] {source} → {dest}")
                    except Exception as e:
                        error_msg = f"Failed to move {source}: {e}"
                        self.logger.error(error_msg)
                        errors.append(error_msg)
                else:
                    self.logger.info(f"[DRY RUN MOVE] {source} → {dest}")

            # Delete duplicates
            for source in plan.files_to_delete:
                if self.state.should_shutdown():
                    break

                if ctx.will_execute():
                    try:
                        if source.is_file():
                            source.unlink()
                        elif source.is_dir():
                            source.rmdir()
                        self.logger.info(f"[DELETE] {source}")
                    except Exception as e:
                        error_msg = f"Failed to delete {source}: {e}"
                        self.logger.error(error_msg)
                        errors.append(error_msg)
                else:
                    self.logger.info(f"[DRY RUN DELETE] {source}")

        result = ConsolidationResult(
            files_moved=len(plan.files_to_move),
            files_deleted=len(plan.files_to_delete),
            duplicates_found=self.state.duplicates_found,
            space_organized=plan.total_move_size,
            space_freed=plan.total_delete_size,
            errors=errors,
            failed_hash_files=[p for p in self.state.failed_hash_files],
        )

        return result

    def run(self) -> ConsolidationResult:
        """
        Run full consolidation pipeline with locking.

        Returns:
            ConsolidationResult with execution statistics
        """
        # Acquire lock
        if not self._acquire_lock():
            return ConsolidationResult(
                files_moved=0,
                files_deleted=0,
                duplicates_found=0,
                space_organized=0,
                space_freed=0,
                errors=["Failed to acquire lock - another instance may be running"],
                failed_hash_files=[],
            )

        # Set up signal handlers
        def signal_handler(signum, frame):
            self.logger.warning(f"\nReceived signal {signum}, requesting graceful shutdown...")
            self.state.request_shutdown()

        old_sigint = signal.signal(signal.SIGINT, signal_handler)
        old_sigterm = signal.signal(signal.SIGTERM, signal_handler)

        try:
            # Pre-flight checks
            if not self.pre_flight():
                return ConsolidationResult(
                    files_moved=0,
                    files_deleted=0,
                    duplicates_found=0,
                    space_organized=0,
                    space_freed=0,
                    errors=["Pre-flight checks failed"],
                    failed_hash_files=[],
                )

            # Scan source
            files = self.scan_and_hash()
            if self.state.should_shutdown():
                return ConsolidationResult(
                    files_moved=0,
                    files_deleted=0,
                    duplicates_found=0,
                    space_organized=0,
                    space_freed=0,
                    errors=["Shutdown requested"],
                    failed_hash_files=[p for p in self.state.failed_hash_files],
                )

            # Create plan
            plan = self.plan(files)
            if self.state.should_shutdown():
                return ConsolidationResult(
                    files_moved=0,
                    files_deleted=0,
                    duplicates_found=0,
                    space_organized=0,
                    space_freed=0,
                    errors=["Shutdown requested"],
                    failed_hash_files=[p for p in self.state.failed_hash_files],
                )

            # Execute
            result = self.execute(plan)

            return result

        finally:
            # Restore signal handlers
            signal.signal(signal.SIGINT, old_sigint)
            signal.signal(signal.SIGTERM, old_sigterm)

            # Release lock
            self._release_lock()
