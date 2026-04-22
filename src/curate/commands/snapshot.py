"""Snapshot command for curate CLI."""

from __future__ import annotations

import json
from pathlib import Path

import click

from curate.lib.scanner import Scanner, Snapshot


@click.command("snapshot")
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["full", "quick", "json"]),
    default="full",
    help="Scan format: full (complete), quick (skip largest files), json (machine-readable)",
)
@click.option("--output", type=click.Path(), help="Output file path (default: stdout)")
@click.option("--diff", type=click.Path(exists=True), help="Compare with previous snapshot")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
def snapshot(path: str, fmt: str, output: str | None, diff: str | None, verbose: bool) -> None:
    """Create a snapshot of file system state.

    Generates a detailed inventory of files, extensions, and disk usage.
    Useful for tracking changes in storage over time.
    """
    scanner = Scanner(path)

    # Choose scan type based on format
    if fmt == "quick":
        snapshot_data = scanner.quick_scan(progress=verbose)
    else:
        snapshot_data = scanner.scan(progress=verbose)

    # Handle diff mode
    if diff:
        diff_result = compare_with_previous(snapshot_data, diff)
        if fmt == "json":
            output_snapshot_diff(diff_result, output)
        else:
            print_human_diff(diff_result)
        return

    # Output based on format
    if fmt == "json":
        output_json_snapshot(snapshot_data, output, scanner)
    else:
        print_human_snapshot(snapshot_data)


def compare_with_previous(current: Snapshot, previous_path: str) -> dict:
    """Compare current snapshot with previous snapshot file."""
    scanner = Scanner(current.path)

    try:
        with open(previous_path) as f:
            previous_data = json.load(f)

        # Handle both full snapshot JSON and diff JSON
        if "by_extension" in previous_data:
            previous = scanner.from_json(json.dumps(previous_data))
            diff = current.diff(previous)
            return {
                "path": diff.path,
                "current_timestamp": diff.timestamp,
                "previous_timestamp": diff.previous_timestamp,
                "files_added": diff.files_added,
                "files_removed": diff.files_removed,
                "size_change_bytes": diff.size_change_bytes,
                "new_extensions": diff.new_extensions,
                "summary": diff.summary,
            }
        else:
            # Already a diff format, return as-is
            return previous_data

    except (json.JSONDecodeError, KeyError) as e:
        click.echo(f"Error loading previous snapshot: {e}", err=True)
        raise click.Abort()


def output_json_snapshot(snapshot: Snapshot, output: str | None, scanner: Scanner) -> None:
    """Output snapshot in JSON format."""
    json_str = scanner.to_json(snapshot)

    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json_str)
        click.echo(f"Snapshot saved to: {output}")
    else:
        click.echo(json_str)


def output_snapshot_diff(diff: dict, output: str | None) -> None:
    """Output snapshot diff in JSON format."""
    json_str = json.dumps(diff, indent=2, ensure_ascii=False)

    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json_str)
        click.echo(f"Diff saved to: {output}")
    else:
        click.echo(json_str)


def print_human_snapshot(snapshot: Snapshot) -> None:
    """Print snapshot in human-readable format."""
    # Convert dataclass to dict if needed
    if hasattr(snapshot, 'to_dict'):
        data = snapshot.to_dict()
    else:
        data = snapshot

    # Header
    timestamp = data["timestamp"][:19].replace("T", " ")
    click.echo(f"Snapshot: {data['path']} ({timestamp})")

    # Disk usage
    disk = data["disk_usage"]
    total_gb = disk["total_bytes"] / (1024**3)
    used_gb = (disk["total_bytes"] - disk["available_bytes"]) / (1024**3)
    click.echo(f"Disk: {used_gb:.1f}G used / {total_gb:.1f}G total ({disk['used_percent']:.1f}%)")

    # Summary
    summary = data["summary"]
    total_size_gb = summary["total_size_bytes"] / (1024**3)
    click.echo(
        f"Files: {summary['total_files']:,} | Dirs: {summary['total_dirs']:,} | Total: {total_size_gb:.1f}G"
    )
    click.echo()

    # By extension
    click.echo("By Extension:")
    for ext, ext_data in list(data["by_extension"].items())[:20]:
        size_str = _format_bytes(ext_data["size_bytes"])
        click.echo(f"  {ext:15} {ext_data['count']:6,} files  {size_str:>8}")
    click.echo()

    # Top directories
    click.echo("Top Directories:")
    for dir_name, dir_data in list(data["top_level_dirs"].items())[:10]:
        size_str = _format_bytes(dir_data["size_bytes"])
        click.echo(f"  {dir_name:30} {size_str:>8} ({dir_data['file_count']:6,} files)")
    click.echo()

    # Largest files
    if data["largest_files"]:
        click.echo("Largest Files:")
        for file_info in data["largest_files"][:10]:
            size_str = _format_bytes(file_info["size_bytes"])
            # Truncate path if too long
            path = file_info["path"]
            if len(path) > 60:
                path = "..." + path[-57:]
            click.echo(f"  {size_str:>8}  {path}")


def print_human_diff(diff: dict) -> None:
    """Print snapshot diff in human-readable format."""
    click.echo(f"Snapshot Diff: {diff['path']}")
    click.echo(f"Current: {diff['current_timestamp'][:19].replace('T', ' ')}")
    click.echo(f"Previous: {diff['previous_timestamp'][:19].replace('T', ' ')}")
    click.echo()

    click.echo(f"Summary: {diff['summary']}")
    click.echo()

    if diff['files_added'] != 0:
        click.echo(f"Files added: {diff['files_added']:+,}")

    if diff['files_removed'] != 0:
        click.echo(f"Files removed: {diff['files_removed']:+,}")

    if diff['size_change_bytes'] != 0:
        change_str = _format_bytes(diff['size_change_bytes'])
        click.echo(f"Size change: {change_str}")

    if diff['new_extensions']:
        click.echo()
        click.echo("New extensions:")
        for ext, count in list(diff['new_extensions'].items())[:10]:
            click.echo(f"  {ext}: {count} files")


def _format_bytes(size_bytes: int) -> str:
    """Format bytes in human-readable format."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"
