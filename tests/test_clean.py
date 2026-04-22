"""Tests for clean command."""

import json
from pathlib import Path
from click.testing import CliRunner

from curate.commands.clean import clean, find_junk_files, remove_empty_directories


def test_find_junk_files(tmp_path):
    """Test junk file detection."""
    # Create junk files
    (tmp_path / "desktop.ini").write_text("junk")
    (tmp_path / "Thumbs.db").write_text("junk")
    (tmp_path / ".DS_Store").write_text("junk")

    # Create non-junk files
    (tmp_path / "document.txt").write_text("important")
    (tmp_path / "photo.jpg").write_text("image")

    patterns = ["desktop.ini", "Thumbs.db", ".DS_Store"]
    junk_files = find_junk_files(tmp_path, patterns)

    assert len(junk_files) == 3
    assert (tmp_path / "desktop.ini") in junk_files
    assert (tmp_path / "Thumbs.db") in junk_files
    assert (tmp_path / ".DS_Store") in junk_files
    assert (tmp_path / "document.txt") not in junk_files
    assert (tmp_path / "photo.jpg") not in junk_files


def test_find_junk_files_recursive(tmp_path):
    """Test junk file detection in subdirectories."""
    # Create nested structure
    subdir = tmp_path / "subdir"
    subdir.mkdir()

    (subdir / "desktop.ini").write_text("junk")
    (tmp_path / "Thumbs.db").write_text("junk")

    patterns = ["desktop.ini", "Thumbs.db"]
    junk_files = find_junk_files(tmp_path, patterns)

    assert len(junk_files) == 2
    assert (subdir / "desktop.ini") in junk_files
    assert (tmp_path / "Thumbs.db") in junk_files


def test_find_junk_files_protected_paths(tmp_path):
    """Test that protected paths are skipped."""
    # Create .git directory
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "desktop.ini").write_text("should be skipped")

    # Create regular directory with junk
    regular_dir = tmp_path / "regular"
    regular_dir.mkdir()
    (regular_dir / "desktop.ini").write_text("should be found")

    patterns = ["desktop.ini"]
    junk_files = find_junk_files(tmp_path, patterns)

    assert len(junk_files) == 1
    assert (regular_dir / "desktop.ini") in junk_files
    assert (git_dir / "desktop.ini") not in junk_files


def test_remove_junk_files_dry_run(tmp_path):
    """Test junk file removal in dry-run mode."""
    # Create test files
    test_file = tmp_path / "desktop.ini"
    test_file.write_text("junk")

    runner = CliRunner()
    result = runner.invoke(
        clean, [str(tmp_path), "--junk", "--json"]
    )

    assert result.exit_code == 0
    # File should still exist after dry-run
    assert test_file.exists()

    # Check JSON output
    data = json.loads(result.output)
    assert data["dry_run"] is True


def test_remove_junk_files_execute(tmp_path):
    """Test junk file removal in execute mode."""
    # Create test files
    junk_file = tmp_path / "desktop.ini"
    junk_file.write_text("junk")

    good_file = tmp_path / "document.txt"
    good_file.write_text("keep this")

    runner = CliRunner()
    result = runner.invoke(
        clean, [str(tmp_path), "--junk", "--execute", "--json"]
    )

    assert result.exit_code == 0
    # Junk file should be deleted
    assert not junk_file.exists()
    # Good file should remain
    assert good_file.exists()

    # Check JSON output
    data = json.loads(result.output)
    assert data["dry_run"] is False
    assert data["junk_deleted"] == 1


def test_empty_directory_detection(tmp_path):
    """Test empty directory detection."""
    # Create empty directory
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    # Create non-empty directory
    nonempty_dir = tmp_path / "nonempty"
    nonempty_dir.mkdir()
    (nonempty_dir / "file.txt").write_text("content")

    # Find empty directories
    from curate.commands.clean import find_empty_directories
    empty_dirs = find_empty_directories(tmp_path)

    assert len(empty_dirs) == 1
    assert empty_dir in empty_dirs
    assert nonempty_dir not in empty_dirs


def test_remove_empty_dirs_dry_run(tmp_path):
    """Test empty directory removal in dry-run mode."""
    # Create empty directory
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    runner = CliRunner()
    result = runner.invoke(
        clean, [str(tmp_path), "--empty-dirs", "--json"]
    )

    assert result.exit_code == 0
    # Directory should still exist after dry-run
    assert empty_dir.exists()


def test_remove_empty_dirs_execute(tmp_path):
    """Test empty directory removal in execute mode."""
    # Create empty directory
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    # Create non-empty directory
    nonempty_dir = tmp_path / "nonempty"
    nonempty_dir.mkdir()
    (nonempty_dir / "file.txt").write_text("content")

    runner = CliRunner()
    result = runner.invoke(
        clean, [str(tmp_path), "--empty-dirs", "--execute", "--json"]
    )

    assert result.exit_code == 0
    # Empty directory should be removed
    assert not empty_dir.exists()
    # Non-empty directory should remain
    assert nonempty_dir.exists()


def test_remove_empty_dirs_multipass(tmp_path):
    """Test multi-pass empty directory removal."""
    # Create nested empty directories
    inner = tmp_path / "level1" / "level2" / "level3"
    inner.mkdir(parents=True)

    runner = CliRunner()
    result = runner.invoke(
        clean, [str(tmp_path), "--empty-dirs", "--execute", "--json"]
    )

    assert result.exit_code == 0
    # All empty directories should be removed
    assert not (tmp_path / "level1").exists()


def test_protected_directories_not_removed(tmp_path):
    """Test that protected directories are not removed."""
    # Create .git directory (empty but protected)
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    # Create regular empty directory
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    runner = CliRunner()
    result = runner.invoke(
        clean, [str(tmp_path), "--empty-dirs", "--execute", "--json"]
    )

    assert result.exit_code == 0
    # .git should not be removed
    assert git_dir.exists()
    # Regular empty directory should be removed
    assert not empty_dir.exists()


def test_custom_patterns(tmp_path):
    """Test custom deletion patterns."""
    # Create files matching custom pattern
    (tmp_path / "test.log").write_text("log")
    (tmp_path / "debug.log").write_text("log")
    (tmp_path / "important.txt").write_text("keep")

    runner = CliRunner()
    result = runner.invoke(
        clean, [str(tmp_path), "--patterns", "*.log", "--execute", "--json"]
    )

    assert result.exit_code == 0
    # Log files should be deleted
    assert not (tmp_path / "test.log").exists()
    assert not (tmp_path / "debug.log").exists()
    # Important file should remain
    assert (tmp_path / "important.txt").exists()


def test_multiple_custom_patterns(tmp_path):
    """Test multiple custom deletion patterns."""
    # Create files
    (tmp_path / "test.log").write_text("log")
    (tmp_path / "temp.tmp").write_text("temp")
    (tmp_path / "keep.txt").write_text("keep")

    runner = CliRunner()
    result = runner.invoke(
        clean,
        [
            str(tmp_path),
            "--patterns",
            "*.log",
            "--patterns",
            "*.tmp",
            "--execute",
            "--json",
        ],
    )

    assert result.exit_code == 0
    # Both patterns should be matched
    assert not (tmp_path / "test.log").exists()
    assert not (tmp_path / "temp.tmp").exists()
    assert (tmp_path / "keep.txt").exists()


def test_apply_all_operations(tmp_path):
    """Test that no flags applies all operations."""
    # Create junk file
    (tmp_path / "desktop.ini").write_text("junk")

    # Create empty directory
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    runner = CliRunner()
    result = runner.invoke(
        clean, [str(tmp_path), "--execute", "--json"]
    )

    assert result.exit_code == 0
    # Both junk and empty dirs should be cleaned
    assert not (tmp_path / "desktop.ini").exists()
    assert not empty_dir.exists()


def test_verbose_output(tmp_path):
    """Test verbose output mode."""
    # Create junk file
    (tmp_path / "desktop.ini").write_text("junk")

    runner = CliRunner()
    result = runner.invoke(
        clean, [str(tmp_path), "--junk", "--verbose"]
    )

    assert result.exit_code == 0
    assert "Found" in result.output or "Would delete" in result.output


def test_json_output_format(tmp_path):
    """Test JSON output format."""
    # Create junk file
    (tmp_path / "desktop.ini").write_text("junk")

    runner = CliRunner()
    result = runner.invoke(
        clean, [str(tmp_path), "--junk", "--execute", "--json"]
    )

    assert result.exit_code == 0

    # Parse JSON output
    data = json.loads(result.output)

    # Check required fields
    assert "junk_deleted" in data
    assert "junk_size" in data
    assert "junk_size_human" in data
    assert "dirs_removed" in data
    assert "permissions_fixed" in data
    assert "dry_run" in data
    assert "errors" in data

    # Check types
    assert isinstance(data["junk_deleted"], int)
    assert isinstance(data["junk_size"], int)
    assert isinstance(data["dirs_removed"], int)
    assert isinstance(data["permissions_fixed"], bool)
    assert isinstance(data["dry_run"], bool)
    assert isinstance(data["errors"], list)


def test_human_readable_size():
    """Test size formatting."""
    from curate.commands.clean import format_size

    assert format_size(100) == "100.00 B"
    assert format_size(1024) == "1.00 KB"
    assert format_size(1024 * 1024) == "1.00 MB"
    assert format_size(1024 * 1024 * 1024) == "1.00 GB"


def test_path_argument_exists(tmp_path):
    """Test that command fails if path doesn't exist."""
    runner = CliRunner()
    result = runner.invoke(
        clean, ["/nonexistent/path"]
    )

    assert result.exit_code != 0


def test_combined_operations(tmp_path):
    """Test combining junk removal and empty dirs."""
    # Create junk file
    (tmp_path / "desktop.ini").write_text("junk")

    # Create empty directory
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    runner = CliRunner()
    result = runner.invoke(
        clean,
        [str(tmp_path), "--junk", "--empty-dirs", "--execute", "--json"],
    )

    assert result.exit_code == 0

    # Parse JSON
    data = json.loads(result.output)

    # Check both operations ran
    assert data["junk_deleted"] >= 1
    assert data["dirs_removed"] >= 1
