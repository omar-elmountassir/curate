"""File system scanner for generating snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from curate.core.progress import ProgressTracker


@dataclass
class ExtensionStats:
    """Statistics for a file extension."""

    count: int = 0
    size_bytes: int = 0
    sample_paths: list[str] = field(default_factory=list)


@dataclass
class DirStats:
    """Statistics for a directory."""

    size_bytes: int = 0
    file_count: int = 0


@dataclass
class FileInfo:
    """Information about a single file."""

    path: str
    size_bytes: int


@dataclass
class Snapshot:
    """Snapshot of file system state."""

    path: str
    timestamp: str
    disk_usage: dict[str, Any]
    summary: dict[str, Any]
    by_extension: dict[str, dict[str, Any]]
    top_level_dirs: dict[str, dict[str, Any]]
    largest_files: list[dict[str, Any]]
    _scanner: Scanner | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert snapshot to dictionary."""
        return {
            "path": self.path,
            "timestamp": self.timestamp,
            "disk_usage": self.disk_usage,
            "summary": self.summary,
            "by_extension": self.by_extension,
            "top_level_dirs": self.top_level_dirs,
            "largest_files": self.largest_files,
        }

    def diff(self, other: Snapshot) -> SnapshotDiff:
        """
        Compare this snapshot with another.

        Args:
            other: Previous snapshot to compare against

        Returns:
            SnapshotDiff object showing changes
        """
        # Simple comparison based on summary stats
        files_added = self.summary["total_files"] - other.summary["total_files"]
        size_change = self.summary["total_size_bytes"] - other.summary["total_size_bytes"]
        files_removed = max(0, -files_added)  # Can't have negative removals
        files_added = max(0, files_added)  # Can't have negative additions

        # Find new extensions
        new_extensions = {}
        for ext, stats in self.by_extension.items():
            if ext not in other.by_extension:
                new_extensions[ext] = stats["count"]

        # Find removed extensions
        removed_extensions = {}
        for ext, stats in other.by_extension.items():
            if ext not in self.by_extension:
                removed_extensions[ext] = stats["count"]

        # Build summary
        parts = []
        if files_added > 0:
            parts.append(f"+{files_added} files")
        if files_removed > 0:
            parts.append(f"-{files_removed} files")
        if new_extensions:
            parts.append(f"{len(new_extensions)} new extensions")
        if removed_extensions:
            parts.append(f"{len(removed_extensions)} removed extensions")
        if size_change != 0:
            parts.append(f"{_format_bytes_static(size_change)} change")

        summary = ", ".join(parts) if parts else "No changes"

        return SnapshotDiff(
            path=self.path,
            timestamp=self.timestamp,
            previous_timestamp=other.timestamp,
            files_added=files_added,
            files_removed=files_removed,
            size_change_bytes=size_change,
            new_extensions=new_extensions,
            summary=summary,
        )


@dataclass
class SnapshotDiff:
    """Difference between two snapshots."""

    path: str
    timestamp: str
    previous_timestamp: str
    files_added: int
    files_removed: int
    size_change_bytes: int
    new_extensions: dict[str, int]
    summary: str


class Scanner:
    """File system scanner for generating snapshots."""

    DEFAULT_SKIP_DIRS = {
        ".git",
        ".svn",
        ".hg",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".pytest_cache",
        ".tox",
    }

    def __init__(
        self,
        path: str,
        skip_dirs: set[str] | None = None,
        max_samples: int = 3,
    ) -> None:
        """
        Initialize scanner.

        Args:
            path: Root path to scan
            skip_dirs: Directory names to skip during scan
            max_samples: Maximum sample paths to keep per extension
        """
        self.path = Path(path).resolve()
        self.skip_dirs = skip_dirs or self.DEFAULT_SKIP_DIRS
        self.max_samples = max_samples

    def scan(self, progress: bool = False) -> Snapshot:
        """
        Perform a full scan including largest files.

        Args:
            progress: Enable progress reporting

        Returns:
            Snapshot object with complete scan data
        """
        return self._scan(largest_files=True, progress=progress)

    def quick_scan(self, progress: bool = False) -> Snapshot:
        """
        Perform a quick scan without largest files.

        Args:
            progress: Enable progress reporting

        Returns:
            Snapshot object without largest files
        """
        return self._scan(largest_files=False, progress=progress)

    def _scan(self, largest_files: bool, progress: bool) -> Snapshot:
        """Internal scan implementation."""
        if not self.path.exists():
            raise FileNotFoundError(f"Path does not exist: {self.path}")

        timestamp = datetime.now().isoformat()

        # Collect file information
        all_files: list[FileInfo] = []
        by_extension: dict[str, ExtensionStats] = {}
        top_level_dirs: dict[str, DirStats] = {}

        with ProgressTracker(desc="Scanning: ") if progress else nullcontext():
            for root, dirs, files in os.walk(self.path):
                # Filter out skipped directories
                dirs[:] = [d for d in dirs if d not in self.skip_dirs]

                root_path = Path(root)

                # Track top-level directory stats
                try:
                    rel_path = root_path.relative_to(self.path)
                    if len(rel_path.parts) == 1:
                        top_dir = str(rel_path)
                        if top_dir not in top_level_dirs:
                            top_level_dirs[top_dir] = DirStats()
                except ValueError:
                    # Path is not relative to scan root
                    pass

                for file in files:
                    file_path = root_path / file
                    try:
                        stat = file_path.stat()
                        size = stat.st_size
                        all_files.append(FileInfo(path=str(file_path), size_bytes=size))

                        # Extension stats
                        ext = file_path.suffix.lower()
                        if ext not in by_extension:
                            by_extension[ext] = ExtensionStats()

                        ext_stats = by_extension[ext]
                        ext_stats.count += 1
                        ext_stats.size_bytes += size

                        if len(ext_stats.sample_paths) < self.max_samples:
                            ext_stats.sample_paths.append(str(file_path))

                        # Top-level directory stats - count all files in top-level dir tree
                        if len(rel_path.parts) >= 1:
                            # Get the top-level directory name
                            top_level_name = rel_path.parts[0]
                            if top_level_name not in top_level_dirs:
                                top_level_dirs[top_level_name] = DirStats()
                            top_level_dirs[top_level_name].size_bytes += size
                            top_level_dirs[top_level_name].file_count += 1

                    except (OSError, PermissionError):
                        # Skip files we can't access
                        continue

        # Build snapshot
        disk_usage = self._get_disk_usage()

        # Sort largest files
        largest_files_data = []
        if largest_files:
            sorted_files = sorted(all_files, key=lambda f: f.size_bytes, reverse=True)[:50]
            largest_files_data = [
                {"path": f.path, "size_bytes": f.size_bytes} for f in sorted_files
            ]

        # Convert extension stats to dicts
        by_extension_dict = {}
        for ext, stats in sorted(
            by_extension.items(), key=lambda x: x[1].size_bytes, reverse=True
        ):
            by_extension_dict[ext] = {
                "count": stats.count,
                "size_bytes": stats.size_bytes,
                "sample_paths": stats.sample_paths,
            }

        # Convert top-level dirs to dicts
        top_level_dirs_dict = {}
        for dir_name, stats in sorted(
            top_level_dirs.items(), key=lambda x: x[1].size_bytes, reverse=True
        ):
            top_level_dirs_dict[dir_name] = {
                "size_bytes": stats.size_bytes,
                "file_count": stats.file_count,
            }

        summary = {
            "total_files": len(all_files),
            "total_dirs": sum(1 for _ in self.path.rglob("*") if _.is_dir()),
            "total_size_bytes": sum(f.size_bytes for f in all_files),
        }

        return Snapshot(
            path=str(self.path),
            timestamp=timestamp,
            disk_usage=disk_usage,
            summary=summary,
            by_extension=by_extension_dict,
            top_level_dirs=top_level_dirs_dict,
            largest_files=largest_files_data,
        )

    def _get_disk_usage(self) -> dict[str, Any]:
        """Get disk usage statistics."""
        import shutil

        usage = shutil.disk_usage(self.path)

        return {
            "total_bytes": usage.total,
            "available_bytes": usage.free,
            "used_percent": (usage.used / usage.total * 100) if usage.total > 0 else 0,
        }

    def diff(self, other: Snapshot) -> SnapshotDiff:
        """
        Compare this snapshot with another.

        Args:
            other: Previous snapshot to compare against

        Returns:
            SnapshotDiff object showing changes
        """
        # Simple comparison based on summary stats
        files_added = self.summary["total_files"] - other.summary["total_files"]
        size_change = self.summary["total_size_bytes"] - other.summary["total_size_bytes"]
        files_removed = -files_added if files_added < 0 else 0

        # Find new extensions
        new_extensions = {}
        for ext, stats in self.by_extension.items():
            if ext not in other.by_extension:
                new_extensions[ext] = stats["count"]

        # Build summary
        parts = []
        if files_added > 0:
            parts.append(f"+{files_added} files")
        if files_removed > 0:
            parts.append(f"-{files_removed} files")
        if new_extensions:
            parts.append(f"{len(new_extensions)} new extensions")
        if size_change != 0:
            parts.append(f"{self._format_bytes(size_change)} change")

        summary = ", ".join(parts) if parts else "No changes"

        return SnapshotDiff(
            path=self.path,
            timestamp=self.timestamp,
            previous_timestamp=other.timestamp,
            files_added=files_added,
            files_removed=files_removed,
            size_change_bytes=size_change,
            new_extensions=new_extensions,
            summary=summary,
        )

    def to_json(self, snapshot: Snapshot) -> str:
        """
        Convert snapshot to JSON string.

        Args:
            snapshot: Snapshot to serialize

        Returns:
            JSON string
        """
        return json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False)

    def from_json(self, json_str: str) -> Snapshot:
        """
        Load snapshot from JSON string.

        Args:
            json_str: JSON string to deserialize

        Returns:
            Snapshot object
        """
        data = json.loads(json_str)
        return Snapshot(
            path=data["path"],
            timestamp=data["timestamp"],
            disk_usage=data["disk_usage"],
            summary=data["summary"],
            by_extension=data["by_extension"],
            top_level_dirs=data["top_level_dirs"],
            largest_files=data["largest_files"],
        )

    @staticmethod
    def _format_bytes(size_bytes: int) -> str:
        """Format bytes in human-readable format."""
        return _format_bytes_static(size_bytes)


def _format_bytes_static(size_bytes: int) -> str:
    """Format bytes in human-readable format (standalone version)."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


# Helper for optional progress tracking
def nullcontext():
    """Null context manager for when progress tracking is disabled."""

    class NullContext:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    return NullContext()


# Import os for os.walk
import os
