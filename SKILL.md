---
name: curate
description: 'Use when organizing, deduplicating, cleaning, or inventorying file systems and directories. Invoke for drive reorganization, file cleanup, duplicate removal, or directory snapshots. Triggers: messy directory, duplicate files, cleanup needed, disk inventory.'
version: 0.1.0
allowed-tools: [Bash]
argument-hint: '[command] [path]'
---

# curate — File System Curation

CLI toolkit for file system organization, deduplication, cleanup, and inventory management.

## Installation

The CLI is installed via `install.sh` or available as `curate` in PATH after installation.

## When to use

Invoke the `curate` skill when:
- User mentions duplicates, duplicate files, deduplication, or redundant files
- User wants to organize or reorganize a directory or drive
- User wants to clean up system files, junk files, or empty directories
- User wants an inventory, snapshot, or audit of a directory
- User wants to merge, consolidate, or reorganize multiple drives or directories
- User mentions file system cleanup, disk space recovery, or file organization

## Commands reference

### `curate snapshot <path>`

Create a detailed inventory of file system state. Useful for tracking changes over time or before/after cleanup operations.

**Key options:**
- `--format FORMAT`: Output format - `full` (complete), `quick` (skip largest files), `json` (machine-readable)
- `--output FILE`: Save snapshot to file instead of stdout
- `--diff FILE`: Compare with previous snapshot file
- `--verbose`: Enable progress reporting

**Examples:**
```bash
# Quick inventory of a drive
curate snapshot /media/drive --format quick

# Full snapshot saved to file
curate snapshot ~/Documents --format json --output ~/docs-snapshot.json

# Compare current state with previous snapshot
curate snapshot /media/drive --diff previous-snapshot.json
```

**Output format:** Human-readable table showing disk usage, file counts, extension breakdown, top directories, and largest files. JSON format includes complete metadata for programmatic analysis.

### `curate dedup <path>`

Find and remove duplicate files using MD5 hash comparison. Keeps one file per duplicate group based on selection strategy.

**Key options:**
- `--min-size BYTES`: Minimum file size to consider (default: 1024)
- `--strategy STRATEGY`: Keeper selection - `deepest` (nested path), `newest` (modification time), `largest` (file size)
- `--include PATTERN`: Include only matching patterns (e.g., `*.jpg`). Can be specified multiple times
- `--exclude PATTERN`: Exclude matching patterns (e.g., `*.tmp`). Can be specified multiple times
- `--skip-dir DIR`: Directory names to skip. Can be specified multiple times
- `--batch-delete`: Use batch deletion mode for large file sets
- `--execute`: Actually delete files (default: dry-run)
- `--json`: Output results as JSON

**Examples:**
```bash
# Dry-run dedup of photos
curate dedup ~/Pictures --include "*.jpg" --include "*.png"

# Execute dedup with newest strategy
curate dedup /media/drive --strategy newest --execute

# Dedup documents, excluding temp files
curate dedup ~/Documents --exclude "*.tmp" --exclude "~*" --execute
```

**Output format:** Summary table showing files scanned, duplicate groups found, files to delete, and space to be freed. JSON format includes complete deletion list and transaction log path.

### `curate sort --path <path>`

Automatically sort files into organized directory structure based on file type detection.

**Key options:**
- `--type TYPE`: Content type - `auto` (detect), `documents`, `music`, `pictures`, `videos`
- `--staging PATH`: Custom staging directory (default: `path/_STAGING`)
- `--execute`: Actually move files (default: dry-run)
- `--json`: Output results as JSON

**Examples:**
```bash
# Auto-detect and sort (dry-run)
curate sort --path ~/Downloads/Mess

# Sort music files into organized structure
curate sort --path ~/Music/unsorted --type music --execute

# Sort with custom staging directory
curate sort --path ~/Pictures --staging ~/Pictures/_STAGING
```

**Output format:** Results table showing total files, files moved, space organized, and category breakdown. Creates organized subdirectories by category (e.g., `Documents/`, `Images/`, `Audio/`).

### `curate clean <path>`

Remove unnecessary files and directories including system junk files and empty directories.

**Key options:**
- `--junk`: Remove system junk files (desktop.ini, Thumbs.db, .DS_Store, etc.)
- `--empty-dirs`: Remove empty directories
- `--permissions`: Fix file permissions
- `--patterns PATTERN`: Additional deletion patterns (can be specified multiple times)
- `--uid UID`: UID for permission fix
- `--gid GID`: GID for permission fix
- `--execute`: Actually perform operations (default: dry-run)
- `--json`: Output results as JSON

**Examples:**
```bash
# Dry-run all cleanup operations
curate clean /media/drive

# Remove junk files
curate clean /media/drive --junk --execute

# Remove empty directories and fix permissions
curate clean ~/Documents --empty-dirs --permissions --uid 1000 --gid 1000 --execute

# Custom cleanup patterns
curate clean ~/Downloads --patterns "*.log" --patterns "*.tmp" --execute
```

**Output format:** Summary showing junk files deleted, size freed, directories removed, and permission fix status. JSON format includes complete operation log.

### `curate consolidate <source> <target>`

Consolidate scattered files from source into organized target directory. Deletes duplicates found in target, moves unique files to staging.

**Key options:**
- `--min-size BYTES`: Minimum file size in bytes (default: 100)
- `--file-type TYPE`: File type preset - `all`, `documents`, `music`, `pictures`, `videos`, `email`
- `--execute`: Actually perform consolidation (default: dry-run)
- `--json`: Output results as JSON

**Examples:**
```bash
# Consolidate documents from external drive
curate consolidate /media/drive ~/Documents --file-type documents

# Consolidate pictures and execute
curate consolidate /media/card ~/Pictures --file-type pictures --execute
```

**Output format:** Summary table showing files moved, duplicates deleted, space organized, and space freed. Creates `TARGET/_STAGING/` directory for triage.

## Workflow patterns

### Assessment workflow
```bash
# Step 1: Create baseline snapshot
curate snapshot /media/drive --format json --output baseline.json

# Step 2: Analyze snapshot (review output manually)
cat baseline.json | jq '.by_extension | to_entries | sort_by(-.value.size_bytes) | .[:10]'
```

### Cleanup workflow
```bash
# Step 1: Dry-run cleanup to see impact
curate clean /media/drive --junk --empty-dirs

# Step 2: Review results, then execute
curate clean /media/drive --junk --empty-dirs --execute

# Step 3: Create after snapshot for comparison
curate snapshot /media/drive --diff baseline.json
```

### Deduplication workflow
```bash
# Step 1: Find duplicates with dry-run
curate dedup ~/Pictures --json > dedup-report.json

# Step 2: Review report and verify strategy
cat dedup-report.json | jq '.files_to_delete, .space_to_free'

# Step 3: Execute with confirmed strategy
curate dedup ~/Pictures --strategy deepest --execute
```

### Sorting workflow
```bash
# Step 1: Auto-detect content type
curate sort --path ~/Downloads/Mess

# Step 2: Execute sort with detected type
curate sort --path ~/Downloads/Mess --type pictures --execute

# Step 3: Review staged files in _STAGING directory
ls -la ~/Downloads/Mess/_STAGING/
```

### Full reorganization workflow
```bash
# Step 1: Baseline snapshot
curate snapshot /media/drive --output before.json

# Step 2: Clean junk and empty dirs
curate clean /media/drive --execute

# Step 3: Remove duplicates
curate dedup /media/drive --execute

# Step 4: Sort files into organized structure
curate sort --path /media/drive --execute

# Step 5: Final snapshot for comparison
curate snapshot /media/drive --output after.json
curate snapshot /media/drive --diff before.json
```

## Safety rules

**CRITICAL AGENT BEHAVIOR:**

1. **ALWAYS run dry-run first** — Never use `--execute` on first run. Always review results before executing destructive operations.

2. **Present results before executing** — Show user the dry-run results and get confirmation before running with `--execute`.

3. **Use --json for programmatic parsing** — When analyzing results programmatically or integrating with other tools, use `--json` output.

4. **Never combine --execute with large operations without confirmation** — For operations affecting >1000 files or >1GB, explicitly warn user and request confirmation.

5. **Always snapshot before destructive operations** — Create a baseline snapshot before running dedup, clean, or sort operations to enable rollback assessment.

6. **Test on small directories first** — When using curate for the first time or on critical data, test on a small subset first.

7. **Verify file system integrity** — Ensure source file system is healthy (no I/O errors, sufficient disk space) before running consolidation operations.

## JSON output format

### snapshot JSON output
```json
{
  "path": "/media/drive",
  "timestamp": "2026-04-22T10:30:00",
  "summary": {
    "total_files": 15234,
    "total_dirs": 856,
    "total_size_bytes": 536870912000
  },
  "disk_usage": {
    "total_bytes": 1000000000000,
    "available_bytes": 463000000000,
    "used_percent": 53.7
  },
  "by_extension": {
    ".jpg": {"count": 4200, "size_bytes": 12582912000},
    ".mp4": {"count": 150, "size_bytes": 322122547200}
  },
  "top_level_dirs": {
    "Documents": {"file_count": 3200, "size_bytes": 53687091200},
    "Pictures": {"file_count": 8900, "size_bytes": 219902325552}
  },
  "largest_files": [
    {"path": "/media/drive/Pictures/video.mp4", "size_bytes": 1073741824}
  ]
}
```

### dedup JSON output
```json
{
  "total_files": 15234,
  "duplicate_groups": 45,
  "files_to_delete": 89,
  "space_to_free": 536870912,
  "deleted_count": 0,
  "space_freed": 0,
  "strategy": "deepest",
  "dry_run": true,
  "transaction_log": "/tmp/curate_dedup_txn_20260422_103000.json",
  "errors": []
}
```

### sort JSON output
```json
{
  "total_files": 500,
  "moved_count": 485,
  "skipped_count": 15,
  "space_organized": 5368709120,
  "by_category": {
    "Documents": 250,
    "Images": 200,
    "Audio": 35
  },
  "errors": [],
  "dry_run": true
}
```

### clean JSON output
```json
{
  "junk_deleted": 42,
  "junk_size": 1048576,
  "junk_size_human": "1.00 MB",
  "dirs_removed": 15,
  "permissions_fixed": true,
  "errors": [],
  "dry_run": true
}
```

### consolidate JSON output
```json
{
  "files_moved": 150,
  "files_deleted": 25,
  "duplicates_found": 25,
  "space_organized": 5368709120,
  "space_freed": 524288000,
  "failed_hash_files": 0,
  "errors": []
}
```