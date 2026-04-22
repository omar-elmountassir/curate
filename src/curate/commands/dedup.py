"""Deduplication command for curate CLI."""

import logging
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import click

from curate.lib.dedup_engine import DedupEngine, DedupResult


@click.command()
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--min-size",
    type=int,
    default=1024,
    help="Minimum file size in bytes (default: 1024)",
)
@click.option(
    "--strategy",
    type=click.Choice(["deepest", "newest", "largest"]),
    default="deepest",
    help="Keeper selection strategy (default: deepest)",
)
@click.option(
    "--include",
    multiple=True,
    help="Include patterns (e.g., '*.jpg'). Can be used multiple times.",
)
@click.option(
    "--exclude",
    multiple=True,
    help="Exclude patterns (e.g., '*.tmp'). Can be used multiple times.",
)
@click.option(
    "--skip-dir",
    multiple=True,
    help="Directory names to skip. Can be used multiple times.",
)
@click.option(
    "--batch-size",
    type=int,
    default=500,
    help="Batch size for batch deletion mode (default: 500)",
)
@click.option(
    "--batch-delete",
    is_flag=True,
    help="Use batch deletion mode (faster for large file sets)",
)
@click.option(
    "--execute",
    is_flag=True,
    help="Actually perform deletions (default: dry-run)",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output results as JSON",
)
@click.option(
    "--verbose", "-v", is_flag=True, help="Enable verbose output"
)
@click.option(
    "--log-file",
    type=click.Path(),
    help="Write log output to file",
)
def dedup(
    path: str,
    min_size: int,
    strategy: str,
    include: tuple,
    exclude: tuple,
    skip_dir: tuple,
    batch_size: int,
    batch_delete: bool,
    execute: bool,
    as_json: bool,
    verbose: bool,
    log_file: str | None,
) -> None:
    """Find and remove duplicate files using MD5 hash.

    Scans PATH for duplicate files (same size + same MD5 hash) and removes
    copies, keeping one file per duplicate group.

    Default is dry-run mode (shows what would be deleted). Use --execute
    to actually delete files.

    Examples:
        curate dedup /media/drive --dry-run
        curate dedup /media/drive --execute --strategy newest
        curate dedup . --include "*.jpg" --include "*.png"
    """
    # Setup logging
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        stream=sys.stdout,
    )

    # Add file handler if log-file specified
    if log_file:
        file_handler = logging.FileHandler(log_file, mode="w")
        file_handler.setLevel(log_level)
        logging.getLogger().addHandler(file_handler)

    logger = logging.getLogger(__name__)

    # Setup transaction log path
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    txn_log_path = Path(tempfile.gettempdir()) / f"curate_dedup_txn_{timestamp}.json" if execute else None

    # Create engine
    engine = DedupEngine(
        path=Path(path),
        min_size=min_size,
        strategy=strategy,
        include_patterns=list(include) if include else None,
        exclude_patterns=list(exclude) if exclude else None,
        skip_dirs=set(skip_dir) if skip_dir else None,
        batch_size=batch_size,
        dry_run=not execute,
        log_file=txn_log_path,
    )

    # Print header
    mode_str = "EXECUTE" if execute else "DRY RUN"
    logger.info("=" * 60)
    logger.info("CURATE DEDUPLICATE")
    logger.info("=" * 60)
    logger.info(f"Path: {path}")
    logger.info(f"Mode: {mode_str}")
    logger.info(f"Strategy: {strategy}")
    logger.info(f"Min size: {min_size} bytes")
    if batch_delete:
        logger.info(f"Batch deletion: enabled (size: {batch_size})")
    logger.info("=" * 60)
    logger.info("")

    # Run deduplication
    try:
        result = engine.run(batch_mode=batch_delete)

        # Print results
        if as_json:
            import json

            click.echo(json.dumps(result.to_dict(), indent=2))
        else:
            _print_human_result(result, execute)

    except Exception as e:
        logger.error(f"\nError: {e}", exc_info=True)
        sys.exit(1)


def _print_human_result(result: DedupResult, execute: bool) -> None:
    """Print human-readable results."""
    print("\n" + "=" * 60)
    print("DEDUPLICATION SUMMARY")
    print("=" * 60)
    print(f"Files scanned:        {result.total_files:,}")
    print(f"Duplicate groups:     {result.duplicate_groups:,}")
    print(f"Files to delete:      {result.files_to_delete:,}")

    if result.space_to_free > 0:
        print(f"Space to free:         {DedupEngine._format_size(result.space_to_free)}")

    if execute:
        print(f"Files deleted:         {result.deleted_count:,}")
        if result.space_freed > 0:
            print(f"Space freed:           {DedupEngine._format_size(result.space_freed)}")
    else:
        print(f"Would delete:          {result.deleted_count:,}")
        if result.space_freed > 0:
            print(f"Would free:            {DedupEngine._format_size(result.space_freed)}")

    if result.errors:
        print(f"\nErrors: {len(result.errors)}")
        for error in result.errors[:5]:
            print(f"  - {error}")
        if len(result.errors) > 5:
            print(f"  ... and {len(result.errors) - 5} more")

    print("=" * 60)

    if not execute:
        print("\nDRY RUN COMPLETE - no files were deleted")
        print("Run with --execute to perform actual deduplication")
