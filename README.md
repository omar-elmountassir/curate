# curate

File system curation toolkit — dedup, sort, clean, snapshot, consolidate.

A CLI tool for organizing, cleaning, and managing file systems. Designed to be invoked by AI agents or used directly.

## Installation

```bash
git clone https://github.com/omar-elmountassir/curate.git
cd curate
./install.sh
```

Requires: Python 3.10+, uv (or pip)

## Commands

| Command | Description |
|---------|-------------|
| `curate snapshot <path>` | Inventory and analysis (read-only) |
| `curate dedup <path>` | Find and remove duplicate files |
| `curate sort <path>` | Organize files by type |
| `curate clean <path>` | Remove junk, empty dirs, fix permissions |
| `curate consolidate <src> <dst>` | Merge source into target |

## Quick Start

```bash
# See what's on a drive
curate snapshot /media/drive

# Find duplicates (dry-run by default)
curate dedup /media/drive

# Remove duplicates
curate dedup /media/drive --execute

# Clean up system files
curate clean /media/drive --junk --empty-dirs --execute

# Sort files by type
curate sort /media/drive --execute

# Full reorganization workflow
curate snapshot /media/drive --format json --output before.json
curate clean /media/drive --execute
curate dedup /media/drive --execute
curate sort /media/drive --execute
curate snapshot /media/drive --format json --output after.json
curate snapshot /media/drive --diff before.json
```

## Safety

All destructive operations default to **dry-run mode**. You must pass `--execute` to actually make changes.

## JSON Output

Every command supports `--json` for machine-readable output, making it easy to integrate with AI agents and scripts.

## Testing

```bash
uv run pytest tests/ -v
```

## License

MIT
