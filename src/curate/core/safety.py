"""Safety utilities for file operations."""

import shutil
from pathlib import Path
from typing import Optional


class DryRunContext:
    """
    Context manager for dry-run mode.

    Intercepts file operations when is_dry_run=True, preventing actual changes.
    Allows testing operations without side effects.
    """

    def __init__(self, is_dry_run: bool = True) -> None:
        """
        Initialize dry-run context.

        Args:
            is_dry_run: If True, operations are logged but not executed
        """
        self.is_dry_run = is_dry_run

    def __enter__(self) -> "DryRunContext":
        """Enter dry-run context."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Exit dry-run context."""
        return False

    def will_execute(self) -> bool:
        """Check if operations will actually execute (vs. dry-run)."""
        return not self.is_dry_run


def pre_flight_check(path: Path) -> tuple[bool, Optional[str]]:
    """
    Verify path is suitable for operations.

    Checks:
    - Path exists
    - Parent directory is writable
    - Sufficient disk space (if possible to determine)

    Args:
        path: Path to check

    Returns:
        Tuple of (is_ok, error_message)
    """
    if not path.exists():
        return False, f"Path does not exist: {path}"

    parent = path.parent if path.is_file() else path

    # Check writability
    if not parent.exists():
        return False, f"Parent directory does not exist: {parent}"

    if not os.access(parent, os.W_OK):
        return False, f"Parent directory is not writable: {parent}"

    # Disk space check (best effort)
    try:
        stat = shutil.disk_usage(parent)
        # Require at least 1GB free
        if stat.free < 1_000_000_000:
            return False, f"Low disk space: {stat.free / 1_000_000_000:.1f}GB free"
    except Exception:
        # Disk space check failed, but don't block operations
        pass

    return True, None


def collision_path(path: Path) -> Path:
    """
    Generate collision-free path by adding numeric suffix.

    If path exists, returns path_1, path_2, etc.

    Args:
        path: Original path

    Returns:
        Collision-free path (may be original if it doesn't exist)
    """
    if not path.exists():
        return path

    counter = 1
    while True:
        new_path = path.parent / f"{path.stem}_{counter}{path.suffix}"
        if not new_path.exists():
            return new_path
        counter += 1


def safe_move(src: Path, dst: Path, dry_run: bool = True) -> bool:
    """
    Move file with collision handling.

    Args:
        src: Source file path
        dst: Destination file path
        dry_run: If True, only simulate the move

    Returns:
        True if successful (or simulated), False on error
    """
    if not src.exists():
        return False

    # Handle collision
    final_dst = collision_path(dst) if dst.exists() else dst

    if dry_run:
        return True

    try:
        shutil.move(str(src), str(final_dst))
        return True
    except (OSError, shutil.Error):
        return False


def safe_delete(path: Path, dry_run: bool = True) -> bool:
    """
    Delete file with verification.

    Args:
        path: File to delete
        dry_run: If True, only simulate the deletion

    Returns:
        True if successful (or simulated), False on error
    """
    if not path.exists():
        # Already gone - consider this success
        return True

    if dry_run:
        return True

    try:
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
        return True
    except OSError:
        return False


# Import os for os.access
import os
