#!/usr/bin/env python3
"""curate — File system curation CLI.

Usage: curate <command> [options]
"""
from __future__ import annotations

import sys
from typing import Any

import click

from curate.commands import clean


# ---------------------------------------------------------------------------
# Shared options
# ---------------------------------------------------------------------------

def verbose_option(f: Any) -> Any:
    """Add --verbose/-v option to command."""
    return click.option(
        "--verbose", "-v", is_flag=True, help="Enable verbose output"
    )(f)


def log_file_option(f: Any) -> Any:
    """Add --log-file option to command."""
    return click.option(
        "--log-file", type=click.Path(), help="Write log output to file"
    )(f)


def json_option(f: Any) -> Any:
    """Add --json option to command."""
    return click.option(
        "--json", "as_json", is_flag=True, help="Output results as JSON"
    )(f)


def common_options(f: Any) -> Any:
    """Add all common options to command."""
    f = verbose_option(f)
    f = log_file_option(f)
    f = json_option(f)
    return f


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------
@click.group()
@click.version_option(version="0.1.0", prog_name="curate")
def cli() -> None:
    """curate — File system curation toolkit."""
    pass


# ---------------------------------------------------------------------------
# curate dedup
# ---------------------------------------------------------------------------
from curate.commands.dedup import dedup
cli.add_command(dedup)


# ---------------------------------------------------------------------------
# curate sort
# ---------------------------------------------------------------------------
from curate.commands.sort import sort as sort_cmd

cli.add_command(sort_cmd)


# ---------------------------------------------------------------------------
# curate clean
# ---------------------------------------------------------------------------
cli.add_command(clean.clean)


# ---------------------------------------------------------------------------
# curate snapshot
# ---------------------------------------------------------------------------
from curate.commands.snapshot import snapshot
cli.add_command(snapshot)


# ---------------------------------------------------------------------------
# curate consolidate
# ---------------------------------------------------------------------------
from curate.commands.consolidate import consolidate as consolidate_cmd

cli.add_command(consolidate_cmd)


# ---------------------------------------------------------------------------
# curate rename
# ---------------------------------------------------------------------------
from curate.commands.rename import rename as rename_cmd

cli.add_command(rename_cmd)


if __name__ == "__main__":
    cli()
