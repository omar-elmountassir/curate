"""Tests for core modules."""

import pytest
from pathlib import Path
from curate.core.hashing import file_hash, file_size, group_by_size
from curate.core.safety import collision_path, safe_delete, DryRunContext


def test_file_hash(tmp_path):
    """Test file hashing."""
    # Create test file
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, World!")

    # Hash should be consistent
    hash1 = file_hash(test_file)
    hash2 = file_hash(test_file)
    assert hash1 == hash2
    assert hash1 is not None
    assert len(hash1) == 32  # MD5 hex digest length


def test_file_hash_nonexistent(tmp_path):
    """Test hashing nonexistent file returns None."""
    result = file_hash(tmp_path / "nonexistent.txt")
    assert result is None


def test_file_size(tmp_path):
    """Test file size."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, World!")
    size = file_size(test_file)
    assert size == 13  # "Hello, World!" is 13 bytes


def test_file_size_nonexistent(tmp_path):
    """Test size of nonexistent file returns None."""
    result = file_size(tmp_path / "nonexistent.txt")
    assert result is None


def test_group_by_size(tmp_path):
    """Test grouping files by size."""
    # Create test files with different sizes
    file1 = tmp_path / "file1.txt"
    file2 = tmp_path / "file2.txt"
    file3 = tmp_path / "file3.txt"

    file1.write_text("A" * 100)
    file2.write_text("B" * 100)  # Same size as file1
    file3.write_text("C" * 200)  # Different size

    files = [
        (file1, 100),
        (file2, 100),
        (file3, 200),
    ]

    groups = group_by_size(files)

    assert len(groups) == 2
    assert len(groups[100]) == 2  # file1 and file2
    assert len(groups[200]) == 1  # file3


def test_collision_path(tmp_path):
    """Test collision path generation."""
    existing = tmp_path / "file.txt"
    existing.write_text("test")

    # Existing file should get suffix
    result = collision_path(existing)
    assert result == tmp_path / "file_1.txt"

    # Non-existing file should be unchanged
    non_existing = tmp_path / "newfile.txt"
    result = collision_path(non_existing)
    assert result == non_existing


def test_safe_delete_dry_run(tmp_path):
    """Test safe_delete in dry-run mode."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("test")

    # Dry-run should not delete
    result = safe_delete(test_file, dry_run=True)
    assert result is True
    assert test_file.exists()


def test_safe_delete_execute(tmp_path):
    """Test safe_delete in execute mode."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("test")

    # Execute should delete
    result = safe_delete(test_file, dry_run=False)
    assert result is True
    assert not test_file.exists()


def test_dry_run_context():
    """Test DryRunContext context manager."""
    # Dry-run mode
    with DryRunContext(is_dry_run=True) as ctx:
        assert ctx.will_execute() is False

    # Execute mode
    with DryRunContext(is_dry_run=False) as ctx:
        assert ctx.will_execute() is True
