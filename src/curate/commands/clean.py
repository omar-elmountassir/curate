"""Clean command implementation."""

import fnmatch
import json
import logging
import os
from dataclasses import dataclass, asdict
from pathlib import Path

import click

from curate.core.safety import safe_delete, DryRunContext
from curate.core.permissions import fix_permissions
from curate.core.progress import ProgressTracker


# Default junk file patterns from cleanup_system_files.sh
DEFAULT_JUNK_PATTERNS = [
    "desktop.ini",
    "Desktop.ini",
    "Thumbs.db",
    "thumbs.db",
    ".DS_Store",
    "ntuser.ini",
    "ntuser.dat*",
    "NTUSER.DAT*",
    "~$*",  # Word temp files
    "~WRL*.tmp",
    "~WRF*.tmp",
    "*.tmp",
    ".~lock.*",
]

# Protected paths that should never be removed
PROTECTED_PATHS = [
    "$RECYCLE.BIN",
    "System Volume Information",
    ".git",
]


@dataclass
class CleanResult:
    """Result of clean operations."""

    junk_deleted: int = 0
    junk_size: int = 0
    dirs_removed: int = 0
    permissions_fixed: bool = False
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def find_junk_files(path: Path, patterns: list[str]) -> list[Path]:
    """
    Find junk files matching patterns.

    Args:
        path: Root path to search
        patterns: List of glob patterns to match

    Returns:
        List of matching file paths
    """
    junk_files = []

    for root, dirs, files in os.walk(path):
        # Skip protected directories
        dirs[:] = [d for d in dirs if not any(protected in d for protected in PROTECTED_PATHS)]

        for filename in files:
            for pattern in patterns:
                if fnmatch.fnmatch(filename, pattern):
                    junk_files.append(Path(root) / filename)
                    break  # Don't add same file multiple times

    return junk_files


def remove_junk_files(
    files: list[Path], execute: bool, verbose: bool = False
) -> tuple[int, int]:
    """
    Remove junk files.

    Args:
        files: List of files to remove
        execute: If True, actually delete; if False, dry-run
        verbose: Enable verbose logging

    Returns:
        Tuple of (count_deleted, total_size)
    """
    count = 0
    total_size = 0

    with DryRunContext(is_dry_run=not execute) as ctx:
        for file_path in files:
            if not file_path.exists():
                continue

            try:
                size = file_path.stat().st_size
                if safe_delete(file_path, dry_run=not ctx.will_execute()):
                    if ctx.will_execute():
                        count += 1
                        total_size += size
                    if verbose:
                        mode = "Deleted" if ctx.will_execute() else "Would delete"
                        click.echo(f"{mode}: {file_path} ({size:,} bytes)")
            except OSError as e:
                if verbose:
                    click.echo(f"Error deleting {file_path}: {e}", err=True)

    return count, total_size


def find_empty_directories(path: Path) -> list[Path]:
    """
    Find empty directories.

    Args:
        path: Root path to search

    Returns:
        List of empty directory paths
    """
    empty_dirs = []

    for root, dirs, files in os.walk(path):
        # Skip protected directories
        dirs[:] = [d for d in dirs if not any(protected in d for protected in PROTECTED_PATHS)]

        # Check if current directory is empty
        current_path = Path(root)
        if not any(current_path.iterdir()):
            empty_dirs.append(current_path)

    return empty_dirs


def remove_empty_directories(
    path: Path, execute: bool, max_passes: int = 10, verbose: bool = False
) -> int:
    """
    Remove empty directories in multiple passes.

    Multiple passes are needed because removing a directory can make its parent empty.

    Args:
        path: Root path to clean
        execute: If True, actually delete; if False, dry-run
        max_passes: Maximum number of passes (default: 10)
        verbose: Enable verbose logging

    Returns:
        Number of directories removed
    """
    total_removed = 0

    with DryRunContext(is_dry_run=not execute) as ctx:
        for pass_num in range(1, max_passes + 1):
            empty_dirs = find_empty_directories(path)

            if not empty_dirs:
                if verbose:
                    click.echo(f"No empty directories found at pass {pass_num}")
                break

            pass_removed = 0
            for dir_path in empty_dirs:
                try:
                    if safe_delete(dir_path, dry_run=not ctx.will_execute()):
                        if ctx.will_execute():
                            pass_removed += 1
                        if verbose:
                            mode = "Removed" if ctx.will_execute() else "Would remove"
                            click.echo(f"{mode}: {dir_path}")
                except OSError as e:
                    if verbose:
                        click.echo(f"Error removing {dir_path}: {e}", err=True)

            if verbose and pass_removed > 0:
                click.echo(f"Pass {pass_num}: Removed {pass_removed} directories")

            total_removed += pass_removed

            if pass_removed == 0:
                # Converged
                break

    return total_removed


def format_size(bytes_size: int) -> str:
    """Format bytes to human-readable size."""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} TB"


@click.command("clean")
@click.argument("path", type=click.Path(exists=True))
@click.option("--junk", is_flag=True, help="Remove system junk files")
@click.option("--empty-dirs", is_flag=True, help="Remove empty directories")
@click.option("--permissions", is_flag=True, help="Fix file permissions")
@click.option(
    "--patterns",
    multiple=True,
    help="Additional deletion patterns (can be used multiple times)",
)
@click.option("--uid", type=int, default=None, help="UID for permission fix")
@click.option("--gid", type=int, default=None, help="GID for permission fix")
@click.option("--execute", is_flag=True, help="Actually perform operations")
@click.option("--json", "as_json", is_flag=True, help="JSON output")
@click.option("--verbose", "-v", is_flag=True)
@click.option("--log-file", type=click.Path())
def clean(
    path: str,
    junk: bool,
    empty_dirs: bool,
    permissions: bool,
    patterns: tuple[str],
    uid: int | None,
    gid: int | None,
    execute: bool,
    as_json: bool,
    verbose: bool,
    log_file: str | None,
) -> None:
    """
    Clean up unnecessary files and directories.

    If no cleanup options are specified (--junk, --empty-dirs, --permissions),
    all cleanup operations will be performed.

    Examples:

        # Dry-run all cleanup operations
        curate clean /media/drive

        # Remove junk files for real
        curate clean /media/drive --junk --execute

        # Remove empty directories and fix permissions
        curate clean /media/drive --empty-dirs --permissions --uid 1000 --gid 1000 --execute

        # Custom deletion patterns
        curate clean /media/drive --patterns "*.log" --patterns "*.tmp" --execute
    """
    # Setup logging
    if log_file:
        logging.basicConfig(
            filename=log_file,
            level=logging.INFO if verbose else logging.WARNING,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )

    # If no flags specified, apply all cleanup operations
    apply_all = not (junk or empty_dirs or permissions or patterns)

    root_path = Path(path).resolve()

    # Build result object
    result = CleanResult()

    # Build patterns list
    all_patterns = list(DEFAULT_JUNK_PATTERNS)
    if patterns:
        all_patterns.extend(patterns)

    # Junk file removal
    if apply_all or junk or patterns:
        if verbose:
            click.echo(f"Scanning for junk files in {root_path}...")

        junk_files = find_junk_files(root_path, all_patterns)

        if verbose:
            click.echo(f"Found {len(junk_files)} junk files")

        if junk_files:
            count, size = remove_junk_files(junk_files, execute, verbose)
            result.junk_deleted = count
            result.junk_size = size

    # Empty directory removal
    if apply_all or empty_dirs:
        if verbose:
            click.echo(f"Scanning for empty directories in {root_path}...")

        dirs_removed = remove_empty_directories(root_path, execute, verbose=verbose)
        result.dirs_removed = dirs_removed

    # Permission fixing
    if apply_all or permissions:
        if verbose:
            click.echo(f"Fixing permissions for {root_path}...")

        perms_ok = fix_permissions(root_path, uid=uid, gid=gid)
        result.permissions_fixed = perms_ok

        if not perms_ok:
            result.errors.append("Permission fixing failed")

    # Output results
    if as_json:
        output = {
            "junk_deleted": result.junk_deleted,
            "junk_size": result.junk_size,
            "junk_size_human": format_size(result.junk_size),
            "dirs_removed": result.dirs_removed,
            "permissions_fixed": result.permissions_fixed,
            "errors": result.errors,
            "dry_run": not execute,
        }
        click.echo(json.dumps(output, indent=2))
    else:
        click.echo("\n=== Clean Summary ===")
        click.echo(f"Mode: {'EXECUTE' if execute else 'DRY-RUN'}")
        click.echo(f"Junk files deleted: {result.junk_deleted:,}")
        click.echo(f"Junk size freed: {format_size(result.junk_size)}")
        click.echo(f"Directories removed: {result.dirs_removed:,}")
        click.echo(f"Permissions fixed: {result.permissions_fixed}")

        if result.errors:
            click.echo("\nErrors:")
            for error in result.errors:
                click.echo(f"  - {error}")
