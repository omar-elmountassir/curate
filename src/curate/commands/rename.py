"""Rename command implementation."""

import json
import logging
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import click

from curate.core.safety import safe_delete, safe_move, DryRunContext, collision_path
from curate.core.hashing import file_hash, file_size


# Patterns to detect
COPY_NUMBER_PATTERN = re.compile(r' \((\d+)\)\.')  # " (N)." before extension
COPY_PATTERN = re.compile(r' - Cop(?:y|ie)(?: \(\d+\))?\.')  # " - Copy." or " - Copie (N)."

# Protected paths to skip
PROTECTED_PATHS = [
    "$RECYCLE.BIN",
    "System Volume Information",
    ".git",
    "Ops",
    "handoff-archive",
]


@dataclass
class RenameAction:
    """Single rename action."""
    original_path: Path
    new_path: Path
    action_type: str  # "rename", "delete_duplicate", "collision_rename"
    pattern_matched: str  # "(N)", "- Copy", "- Copie"
    file_size: int


@dataclass
class RenameResult:
    """Result of rename operations."""
    total_scanned: int = 0
    pattern_files_found: int = 0
    renamed: int = 0
    duplicates_deleted: int = 0
    collision_renamed: int = 0
    skipped: int = 0
    space_freed: int = 0
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def find_copy_files(path: Path) -> list[tuple[Path, str]]:
    """
    Find files matching copy patterns.

    Args:
        path: Root path to search

    Returns:
        List of (file_path, pattern_matched) tuples
    """
    copy_files = []

    for root, dirs, files in os.walk(path):
        # Skip protected directories
        dirs[:] = [d for d in dirs if not any(protected in d for protected in PROTECTED_PATHS)]

        for filename in files:
            # Check for (N) pattern
            match = COPY_NUMBER_PATTERN.search(filename)
            if match:
                copy_files.append((Path(root) / filename, "(N)"))
                continue

            # Check for - Copy/- Copie pattern
            match = COPY_PATTERN.search(filename)
            if match:
                # Determine which variant matched
                if "Copie" in filename:
                    copy_files.append((Path(root) / filename, "- Copie"))
                else:
                    copy_files.append((Path(root) / filename, "- Copy"))

    return copy_files


def get_clean_name(file_path: Path, pattern: str) -> Optional[Path]:
    """
    Get clean name by removing pattern from filename.

    Args:
        file_path: Original file path
        pattern: Pattern that matched ("(N)", "- Copy", "- Copie")

    Returns:
        Clean path with pattern removed, or None if pattern doesn't match
    """
    filename = file_path.name
    stem = file_path.stem
    suffix = file_path.suffix

    if pattern == "(N)":
        # Remove " (N)" before extension
        match = COPY_NUMBER_PATTERN.search(filename)
        if match:
            number = match.group(1)
            # Remove " (N)" from stem
            clean_stem = stem.removesuffix(f" ({number})")
            return file_path.parent / f"{clean_stem}{suffix}"

    elif pattern in ("- Copy", "- Copie"):
        # Remove " - Copy" or " - Copie" (with optional number)
        # The pattern includes the extension separator, so we need to work with the full filename
        match = COPY_PATTERN.search(filename)
        if match:
            # Remove the matched pattern from the filename
            clean_filename = COPY_PATTERN.sub(".", filename)  # Replace with just the dot
            return file_path.parent / clean_filename

    return None


def determine_action(
    file_path: Path,
    clean_path: Path,
    pattern: str
) -> tuple[str, Optional[Path]]:
    """
    Determine what action to take for a file.

    Args:
        file_path: Original file path
        clean_path: Clean path (pattern removed)
        pattern: Pattern that matched

    Returns:
        Tuple of (action_type, final_path)
        action_type: "rename", "delete_duplicate", "collision_rename", "skip"
        final_path: Target path for rename (None for delete/skip)
    """
    # Check if clean name exists
    if not clean_path.exists():
        # No original - this IS the only copy, just has a dirty name
        return "rename", clean_path

    # Original exists - check content
    original_hash = file_hash(file_path)
    clean_hash = file_hash(clean_path)

    if original_hash is None:
        return "skip", None

    if clean_hash is None:
        # Can't read original - skip to be safe
        return "skip", None

    if original_hash == clean_hash:
        # Same content - duplicate
        return "delete_duplicate", None
    else:
        # Different content - need collision handling
        collision_free = collision_path(clean_path)
        return "collision_rename", collision_free


def process_renames(
    copy_files: list[tuple[Path, str]],
    execute: bool,
    verbose: bool = False
) -> RenameResult:
    """
    Process copy files and determine actions.

    Args:
        copy_files: List of (file_path, pattern) tuples
        execute: If True, actually perform operations
        verbose: Enable verbose logging

    Returns:
        RenameResult with statistics
    """
    result = RenameResult()
    result.total_scanned = len(copy_files)

    # Sort by reverse order within each directory to process highest (N) first
    # This prevents conflicts when renaming file (2).txt and file (1).txt
    def sort_key(item):
        path, pattern = item
        # Group by parent directory and stem
        return (str(path.parent), path.stem, item)

    # Sort to process highest numbers first
    copy_files.sort(key=sort_key, reverse=True)

    with DryRunContext(is_dry_run=not execute) as ctx:
        for file_path, pattern in copy_files:
            if not file_path.exists():
                result.skipped += 1
                continue

            # Get clean name
            clean_path = get_clean_name(file_path, pattern)
            if clean_path is None:
                result.skipped += 1
                continue

            result.pattern_files_found += 1

            # Get file size
            size = file_size(file_path)
            if size is None:
                result.errors.append(f"Cannot read file size: {file_path}")
                result.skipped += 1
                continue

            # Determine action
            action_type, final_path = determine_action(file_path, clean_path, pattern)

            if action_type == "skip":
                result.skipped += 1
                if verbose:
                    click.echo(f"Skip: {file_path}")
                continue

            if action_type == "delete_duplicate":
                if ctx.will_execute():
                    if safe_delete(file_path, dry_run=False):
                        result.duplicates_deleted += 1
                        result.space_freed += size
                        if verbose:
                            click.echo(f"Deleted duplicate: {file_path}")
                    else:
                        result.errors.append(f"Failed to delete: {file_path}")
                else:
                    result.duplicates_deleted += 1
                    result.space_freed += size
                    if verbose:
                        click.echo(f"Would delete duplicate: {file_path}")

            elif action_type == "rename":
                if ctx.will_execute():
                    if safe_move(file_path, final_path, dry_run=False):
                        result.renamed += 1
                        if verbose:
                            click.echo(f"Renamed: {file_path} -> {final_path}")
                    else:
                        result.errors.append(f"Failed to rename: {file_path}")
                else:
                    result.renamed += 1
                    if verbose:
                        click.echo(f"Would rename: {file_path} -> {final_path}")

            elif action_type == "collision_rename":
                if ctx.will_execute():
                    if safe_move(file_path, final_path, dry_run=False):
                        result.collision_renamed += 1
                        if verbose:
                            click.echo(f"Renamed (collision): {file_path} -> {final_path}")
                    else:
                        result.errors.append(f"Failed to rename: {file_path}")
                else:
                    result.collision_renamed += 1
                    if verbose:
                        click.echo(f"Would rename (collision): {file_path} -> {final_path}")

    return result


def format_size(bytes_size: int) -> str:
    """Format bytes to human-readable size."""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} TB"


@click.command("rename")
@click.argument("path", type=click.Path(exists=True))
@click.option("--execute", is_flag=True, help="Actually rename/delete (default: dry-run)")
@click.option("--json", "as_json", is_flag=True, help="JSON output")
@click.option("--verbose", "-v", is_flag=True)
@click.option("--log-file", type=click.Path())
def rename(
    path: str,
    execute: bool,
    as_json: bool,
    verbose: bool,
    log_file: str | None,
) -> None:
    """
    Clean up file naming patterns from copy operations.

    Detects and handles:
    - Windows copy pattern: "file (1).ext", "file (2).ext"
    - Windows copy suffix: "file - Copy.ext", "file - Copie.ext"

    For each matched file:
    - If original doesn't exist: rename to clean name
    - If original exists with same content: delete duplicate
    - If original exists with different content: rename with collision suffix

    Examples:

        # Dry-run to see what would happen
        curate rename /media/drive

        # Actually perform the operations
        curate rename /media/drive --execute

        # Verbose output
        curate rename /media/drive --verbose
    """
    # Setup logging
    if log_file:
        logging.basicConfig(
            filename=log_file,
            level=logging.INFO if verbose else logging.WARNING,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )

    root_path = Path(path).resolve()

    if verbose:
        click.echo(f"Scanning {root_path} for copy patterns...")

    # Find files matching patterns
    copy_files = find_copy_files(root_path)

    if verbose:
        click.echo(f"Found {len(copy_files)} files matching copy patterns")

    # Process renames
    result = process_renames(copy_files, execute, verbose)

    # Output results
    if as_json:
        output = {
            "total_scanned": result.total_scanned,
            "pattern_files_found": result.pattern_files_found,
            "renamed": result.renamed,
            "duplicates_deleted": result.duplicates_deleted,
            "collision_renamed": result.collision_renamed,
            "skipped": result.skipped,
            "space_freed": result.space_freed,
            "space_freed_human": format_size(result.space_freed),
            "errors": result.errors,
            "dry_run": not execute,
        }
        click.echo(json.dumps(output, indent=2))
    else:
        click.echo("\n=== Rename Summary ===")
        click.echo(f"Mode: {'EXECUTE' if execute else 'DRY-RUN'}")
        click.echo(f"Files scanned: {result.total_scanned:,}")
        click.echo(f"Pattern files found: {result.pattern_files_found:,}")
        click.echo("")
        click.echo("Actions:")
        click.echo(f"  Rename (no original):        {result.renamed:,} files")
        click.echo(f"  Delete (true duplicate):     {result.duplicates_deleted:,} files  ({format_size(result.space_freed)})")
        click.echo(f"  Rename (different content):  {result.collision_renamed:,} files")
        click.echo(f"  Skipped:                     {result.skipped:,} files")

        if result.errors:
            click.echo("\nErrors:")
            for error in result.errors:
                click.echo(f"  - {error}")

        if not execute:
            click.echo("\nRun with --execute to apply.")
