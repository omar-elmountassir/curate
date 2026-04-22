# `curate rename` Command Implementation Report

## Summary

Successfully implemented the `curate rename` command for cleaning up file naming patterns from copy operations. The command detects and handles Windows-style copy patterns: `(N)` suffixes and `- Copy`/`- Copie` suffixes.

## Files Created/Modified

### Created Files
1. **`src/curate/commands/rename.py`** (375 lines)
   - Main command implementation
   - Pattern detection for `(N)`, `- Copy`, `- Copie`
   - Content-aware duplicate detection using file hashing
   - Collision handling for different content
   - Dry-run and execute modes
   - JSON and human-readable output formats

2. **`tests/test_rename.py`** (347 lines)
   - Comprehensive test suite with 26 test cases
   - Pattern detection tests
   - Clean name generation tests
   - Action determination tests
   - Integration tests for all scenarios
   - Edge case handling tests
   - All tests passing: ✓

### Modified Files
1. **`src/curate/cli.py`** (+8 lines)
   - Added import for `rename` command
   - Registered command with CLI group

## Test Results

```
26 passed in 0.06s
```

### Test Coverage
- Pattern detection for `(N)`, `- Copy`, `- Copie`
- Clean name generation preserving extensions
- Action determination (rename, delete, collision, skip)
- Dry-run mode (no changes)
- Execute mode (performs operations)
- Duplicate deletion (same content)
- Collision handling (different content)
- Reverse order processing (higher N first)
- JSON output format
- Verbose output
- Summary output
- Protected directory skipping
- Inaccessible file handling
- Empty directories
- Mixed patterns

## Command Features

### Patterns Detected
1. **`(N)` suffix** — Windows copy/download pattern
   - `filename (1).ext` → `filename.ext`
   - `filename (10).ext` → `filename.ext`

2. **`- Copy` / `- Copie`** — Windows explicit copy
   - `filename - Copy.ext` → `filename.ext`
   - `filename - Copie (2).ext` → `filename.ext`

3. **DOES NOT touch `_N`** — Preserves legitimate patterns
   - `photo_1.jpg` → untouched (burst photos, track numbers)

### Action Logic

For each matched file:
1. **No original exists** → Rename to clean name
2. **Original exists with same content** → Delete duplicate
3. **Original exists with different content** → Rename with collision suffix

### Safety Features
- Default dry-run mode (requires `--execute` flag)
- Content-aware duplicate detection using MD5 hashing
- Collision-free path generation
- Protected directory skipping (Ops/, handoff-archive/, etc.)
- Graceful error handling (inaccessible files, permissions)
- Reverse-order processing (highest (N) first)

### Usage Examples

```bash
# Dry-run to see what would happen
curate rename /media/drive

# Actually perform the operations
curate rename /media/drive --execute

# Verbose output
curate rename /media/drive --verbose

# JSON output
curate rename /media/drive --json
```

### Output Format

```
=== Rename Summary ===
Mode: DRY-RUN
Files scanned: 84,487
Pattern files found: 3,453

Actions:
  Rename (no original):        1,234 files
  Delete (true duplicate):       567 files  (2.3 GB)
  Rename (different content):    652 files
  Skipped:                         12 files

Run with --execute to apply.
```

## End-to-End Verification

Tested with real files:
- `file.txt` (original)
- `file (1).txt` (different content) → `file_1.txt`
- `file (2).txt` (different content) → `file_2.txt`
- `doc - Copy.txt` → `doc.txt`

Result: ✓ All operations performed correctly

## Integration Points

The command follows existing patterns in the curate CLI:
- Uses `DryRunContext` from `core/safety.py`
- Uses `file_hash()` from `core/hashing.py`
- Uses `collision_path()` from `core/safety.py`
- Follows Click command patterns from other commands
- Matches output formatting style

## Issues

None detected. All tests passing, end-to-end verification successful.
