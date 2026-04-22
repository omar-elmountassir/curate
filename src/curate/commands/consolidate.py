"""Consolidate command implementation."""

import click
from pathlib import Path
from typing import Optional

from curate.lib.consolidator import Consolidator, FILE_TYPE_PRESETS


@click.command("consolidate")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.argument("target", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--min-size",
    default=100,
    type=int,
    help="Minimum file size in bytes (default: 100)"
)
@click.option(
    "--file-type",
    type=click.Choice(["all", "documents", "music", "pictures", "videos", "email"]),
    default="all",
    help="File type preset to consolidate (default: all)"
)
@click.option(
    "--execute",
    is_flag=True,
    help="Actually perform consolidation (default: dry-run)"
)
@click.option("--json", "as_json", is_flag=True, help="JSON output")
@click.option("--verbose", "-v", is_flag=True)
@click.option(
    "--log-file",
    type=click.Path(path_type=Path),
    help="Write log output to file"
)
def consolidate(
    source: Path,
    target: Path,
    min_size: int,
    file_type: str,
    execute: bool,
    as_json: bool,
    verbose: bool,
    log_file: Optional[Path],
) -> None:
    """
    Consolidate scattered files into organized directory.

    Scans SOURCE directory for files matching FILE_TYPE, then:
    - Deletes duplicates found in TARGET directory
    - Moves unique files to TARGET/_STAGING/ for triage

    Default is dry-run mode. Use --execute to actually perform operations.

    Examples:
        curate consolidate /media/drive /home/user/Documents --file-type documents
        curate consolidate /media/drive /home/user/Pictures --file-type pictures --execute
    """
    # Create consolidator
    consolidator = Consolidator(
        source=source,
        target=target,
        min_size=min_size,
        file_type=file_type,
        dry_run=not execute,
        log_file=log_file,
    )

    # Run consolidation
    result = consolidator.run()

    # Output results
    if as_json:
        import json
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        _print_human_readable(result, file_type, source, target, execute)


def _print_human_readable(result, file_type: str, source: Path, target: Path, execute: bool) -> None:
    """Print human-readable summary table."""
    click.echo()
    click.echo("=" * 60)
    click.echo("CONSOLIDATION SUMMARY")
    click.echo("=" * 60)
    click.echo(f"Source:     {source}")
    click.echo(f"Target:     {target}")
    click.echo(f"File type:  {file_type}")
    click.echo(f"Mode:       {'EXECUTE' if execute else 'DRY RUN'}")
    click.echo("-" * 60)
    click.echo(f"Files moved:         {result.files_moved}")
    click.echo(f"Files deleted:       {result.files_deleted}")
    click.echo(f"Duplicates found:    {result.duplicates_found}")
    click.echo(f"Space organized:     {_format_size(result.space_organized)}")
    click.echo(f"Space freed:         {_format_size(result.space_freed)}")

    if result.failed_hash_files:
        click.echo(f"Failed hashes:       {len(result.failed_hash_files)}")

    if result.errors:
        click.echo()
        click.echo("Errors:")
        for error in result.errors:
            click.echo(f"  - {error}")

    click.echo("=" * 60)


def _format_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"
