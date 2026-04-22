"""curate sort command."""

from pathlib import Path
from typing import Any

import click

from curate.lib.sorter import Sorter


def path_option(f: Any) -> Any:
    """Add --path option to command."""
    return click.option(
        "--path",
        type=click.Path(exists=True, path_type=Path),
        required=True,
        help="Path to sort",
    )(f)


def type_option(f: Any) -> Any:
    """Add --type option to command."""
    return click.option(
        "--type",
        "sort_type",
        type=click.Choice(["auto", "documents", "music", "pictures", "videos"]),
        default="auto",
        help="Type of content to sort (default: auto)",
    )(f)


def staging_option(f: Any) -> Any:
    """Add --staging option to command."""
    return click.option(
        "--staging",
        type=click.Path(path_type=Path),
        help="Staging directory for sorted files (default: path/_STAGING)",
    )(f)


def execute_option(f: Any) -> Any:
    """Add --execute option to command."""
    return click.option(
        "--execute",
        is_flag=True,
        help="Actually move files (default: dry-run)",
    )(f)


@click.command()
@path_option
@type_option
@staging_option
@execute_option
@click.option(
    "--verbose", "-v", is_flag=True, help="Enable verbose output"
)
@click.option(
    "--json", "as_json", is_flag=True, help="Output results as JSON"
)
def sort(
    path: Path,
    sort_type: str,
    staging: Path | None,
    execute: bool,
    verbose: bool,
    as_json: bool,
) -> None:
    """Sort files into organized directory structure.

    Automatically detects file type by scanning extension distribution.
    Supports documents, music, pictures, and videos.

    Examples:

        # Auto-detect and sort (dry-run)
        curate sort --path ~/Downloads/Mess

        # Sort music files
        curate sort --path ~/Music/_STAGING --type music

        # Actually move files (not dry-run)
        curate sort --path ~/Pictures/_STAGING --execute

        # Sort with custom staging directory
        curate sort --path ~/Videos --staging ~/Videos/_STAGING
    """
    import json

    dry_run = not execute

    # Initialize sorter
    sorter = Sorter(
        path=path,
        sort_type=sort_type,
        staging=staging,
        dry_run=dry_run,
    )

    # Auto-detect if needed
    if sort_type == "auto":
        detected = sorter.detect_type()
        if verbose:
            click.echo(f"Detected type: {detected}")
        if detected == "mixed":
            click.echo(
                "Warning: Mixed content detected. "
                "Files will be categorized by basic type.",
                err=True,
            )

    # Run sort
    click.echo(f"Sorting {'(dry-run)' if dry_run else '(executing)'}...")
    result = sorter.run()

    # Output results
    if as_json:
        output = {
            "total_files": result.total_files,
            "moved_count": result.moved_count,
            "skipped_count": result.skipped_count,
            "space_organized": result.space_organized,
            "by_category": result.by_category,
            "errors": result.errors,
            "dry_run": dry_run,
        }
        click.echo(json.dumps(output, indent=2))
    else:
        # Human-readable table
        click.echo()
        click.echo("=" * 60)
        click.echo("SORT RESULTS")
        click.echo("=" * 60)
        click.echo(f"Total files:      {result.total_files:,}")
        click.echo(f"Files moved:      {result.moved_count:,}")
        click.echo(f"Files skipped:    {result.skipped_count:,}")
        click.echo(f"Space organized:  {result.space_organized:,} bytes")
        if result.space_organized > 0:
            click.echo(
                f"                  ({result.space_organized / (1024**3):.2f} GB)"
            )

        # Category breakdown
        if result.by_category:
            click.echo()
            click.echo("Files by category:")
            for category, count in sorted(result.by_category.items()):
                click.echo(f"  {category}: {count:,}")

        # Errors
        if result.errors:
            click.echo()
            click.echo(f"Errors: {len(result.errors)}")
            if verbose:
                for error in result.errors[:10]:
                    click.echo(f"  - {error}")
                if len(result.errors) > 10:
                    click.echo(f"  ... and {len(result.errors) - 10} more")

        click.echo("=" * 60)

        # Dry-run warning
        if dry_run:
            click.echo()
            click.echo(
                "DRY-RUN MODE: No files were actually moved. "
                "Use --execute to perform the sort.",
                err=True,
            )
