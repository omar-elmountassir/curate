"""Tests for rename command."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from curate.commands.rename import (
    rename,
    find_copy_files,
    get_clean_name,
    determine_action,
    COPY_NUMBER_PATTERN,
    COPY_PATTERN,
)


@pytest.fixture
def runner():
    """Click CLI runner."""
    return CliRunner()


@pytest.fixture
def temp_dir(tmp_path):
    """Temporary directory for test files."""
    return tmp_path


class TestPatternDetection:
    """Test pattern detection."""

    def test_copy_number_pattern(self):
        """Test (N) pattern detection."""
        assert COPY_NUMBER_PATTERN.search("file (1).txt")
        assert COPY_NUMBER_PATTERN.search("file (2).jpg")
        assert COPY_NUMBER_PATTERN.search("file (10).png")
        assert not COPY_NUMBER_PATTERN.search("file.txt")
        assert not COPY_NUMBER_PATTERN.search("file_1.txt")

    def test_copy_pattern(self):
        """Test - Copy/- Copie pattern detection."""
        assert COPY_PATTERN.search("file - Copy.txt")
        assert COPY_PATTERN.search("file - Copie.txt")
        assert COPY_PATTERN.search("file - Copie (2).txt")
        assert not COPY_PATTERN.search("file.txt")
        assert not COPY_PATTERN.search("file-copy.txt")


class TestFindCopyFiles:
    """Test finding copy files."""

    def test_finds_copy_number_files(self, temp_dir):
        """Test finding files with (N) pattern."""
        (temp_dir / "file.txt").write_text("original")
        (temp_dir / "file (1).txt").write_text("copy1")
        (temp_dir / "file (2).txt").write_text("copy2")

        copy_files = find_copy_files(temp_dir)

        assert len(copy_files) == 2
        patterns = [p for _, p in copy_files]
        assert all(p == "(N)" for p in patterns)
        paths = [str(p) for p, _ in copy_files]
        assert "file (1).txt" in " ".join(paths)
        assert "file (2).txt" in " ".join(paths)

    def test_finds_copy_suffix_files(self, temp_dir):
        """Test finding files with - Copy pattern."""
        (temp_dir / "file - Copy.txt").write_text("copy")
        (temp_dir / "file - Copie.txt").write_text("copie")
        (temp_dir / "file - Copie (2).txt").write_text("copie2")

        copy_files = find_copy_files(temp_dir)

        assert len(copy_files) == 3
        patterns = [p for _, p in copy_files]
        assert "- Copy" in patterns
        assert "- Copie" in patterns

    def test_skips_protected_directories(self, temp_dir):
        """Test that protected directories are skipped."""
        (temp_dir / "Ops").mkdir()
        (temp_dir / "Ops" / "file (1).txt").write_text("protected")
        (temp_dir / "handoff-archive").mkdir()
        (temp_dir / "handoff-archive" / "file (2).txt").write_text("protected")

        copy_files = find_copy_files(temp_dir)

        assert len(copy_files) == 0

    def test_skips_normal_files(self, temp_dir):
        """Test that normal files are not flagged."""
        (temp_dir / "file.txt").write_text("normal")
        (temp_dir / "file_1.txt").write_text("underscore")
        (temp_dir / "photo_1.jpg").write_text("photo")

        copy_files = find_copy_files(temp_dir)

        assert len(copy_files) == 0


class TestGetCleanName:
    """Test clean name generation."""

    def test_removes_copy_number(self, temp_dir):
        """Test removing (N) pattern."""
        file_path = temp_dir / "file (1).txt"
        clean = get_clean_name(file_path, "(N)")

        assert clean == temp_dir / "file.txt"
        assert clean.parent == file_path.parent

    def test_removes_copy_suffix(self, temp_dir):
        """Test removing - Copy pattern."""
        file_path = temp_dir / "file - Copy.txt"
        clean = get_clean_name(file_path, "- Copy")

        assert clean == temp_dir / "file.txt"

    def test_removes_copie_suffix(self, temp_dir):
        """Test removing - Copie pattern."""
        file_path = temp_dir / "file - Copie (2).txt"
        clean = get_clean_name(file_path, "- Copie")

        assert clean == temp_dir / "file.txt"

    def test_preserves_extension(self, temp_dir):
        """Test that extensions are preserved."""
        for pattern, filename in [
            ("(N)", "photo (1).jpg"),
            ("- Copy", "document - Copy.pdf"),
            ("- Copie", "video - Copie.mp4"),
        ]:
            file_path = temp_dir / filename
            clean = get_clean_name(file_path, pattern)
            assert clean.suffix == file_path.suffix


class TestDetermineAction:
    """Test action determination."""

    def test_rename_when_no_original(self, temp_dir):
        """Test rename when original doesn't exist."""
        copy_file = temp_dir / "file (1).txt"
        copy_file.write_text("copy content")

        clean_path = temp_dir / "file.txt"
        action, final_path = determine_action(copy_file, clean_path, "(N)")

        assert action == "rename"
        assert final_path == clean_path

    def test_delete_duplicate_when_same_content(self, temp_dir):
        """Test delete when original exists with same content."""
        content = "same content"
        original = temp_dir / "file.txt"
        original.write_text(content)

        copy_file = temp_dir / "file (1).txt"
        copy_file.write_text(content)

        clean_path = temp_dir / "file.txt"
        action, final_path = determine_action(copy_file, clean_path, "(N)")

        assert action == "delete_duplicate"
        assert final_path is None

    def test_collision_rename_when_different_content(self, temp_dir):
        """Test collision rename when content differs."""
        original = temp_dir / "file.txt"
        original.write_text("original content")

        copy_file = temp_dir / "file (1).txt"
        copy_file.write_text("different content")

        clean_path = temp_dir / "file.txt"
        action, final_path = determine_action(copy_file, clean_path, "(N)")

        assert action == "collision_rename"
        assert final_path != clean_path
        assert final_path.stem.startswith("file_")

    def test_skip_when_cannot_read_copy(self, temp_dir):
        """Test skip when copy file can't be read."""
        original = temp_dir / "file.txt"
        original.write_text("content")

        # Create a file we can't read (no permissions)
        copy_file = temp_dir / "file (1).txt"
        copy_file.write_text("content")
        os.chmod(copy_file, 0o000)

        clean_path = temp_dir / "file.txt"
        action, final_path = determine_action(copy_file, clean_path, "(N)")

        # Restore permissions for cleanup
        os.chmod(copy_file, 0o644)

        assert action == "skip"


class TestRenameCommand:
    """Test rename command integration."""

    def test_dry_run_no_changes(self, runner, temp_dir):
        """Test dry-run doesn't modify files."""
        (temp_dir / "file (1).txt").write_text("copy")

        result = runner.invoke(rename, [str(temp_dir)])

        assert result.exit_code == 0
        assert (temp_dir / "file (1).txt").exists()  # Still exists
        assert not (temp_dir / "file.txt").exists()  # Not renamed

    def test_performs_rename_with_execute(self, runner, temp_dir):
        """Test --execute actually renames."""
        (temp_dir / "file (1).txt").write_text("copy")

        result = runner.invoke(rename, [str(temp_dir), "--execute"])

        assert result.exit_code == 0
        assert not (temp_dir / "file (1).txt").exists()  # Gone
        assert (temp_dir / "file.txt").exists()  # Renamed

    def test_deletes_duplicate_with_execute(self, runner, temp_dir):
        """Test duplicate deletion with --execute."""
        content = "same content"
        (temp_dir / "file.txt").write_text(content)
        (temp_dir / "file (1).txt").write_text(content)

        result = runner.invoke(rename, [str(temp_dir), "--execute"])

        assert result.exit_code == 0
        assert (temp_dir / "file.txt").exists()  # Original remains
        assert not (temp_dir / "file (1).txt").exists()  # Duplicate deleted

    def test_handles_collision_with_execute(self, runner, temp_dir):
        """Test collision handling with --execute."""
        (temp_dir / "file.txt").write_text("original")
        (temp_dir / "file (1).txt").write_text("different")

        result = runner.invoke(rename, [str(temp_dir), "--execute"])

        assert result.exit_code == 0
        assert (temp_dir / "file.txt").exists()  # Original
        assert not (temp_dir / "file (1).txt").exists()  # Renamed away
        # Should have file_1.txt or similar
        assert any(p.name.startswith("file_") for p in temp_dir.glob("file_*.txt"))

    def test_reverse_order_processing(self, runner, temp_dir):
        """Test that higher numbers are processed first."""
        (temp_dir / "file.txt").write_text("original")
        (temp_dir / "file (1).txt").write_text("copy1")
        (temp_dir / "file (2).txt").write_text("copy2")

        result = runner.invoke(rename, [str(temp_dir), "--execute"])

        assert result.exit_code == 0
        assert (temp_dir / "file.txt").exists()
        # Both copies should be deleted (duplicates)
        assert not (temp_dir / "file (1).txt").exists()
        assert not (temp_dir / "file (2).txt").exists()

    def test_json_output(self, runner, temp_dir):
        """Test JSON output format."""
        (temp_dir / "file (1).txt").write_text("copy")

        result = runner.invoke(rename, [str(temp_dir), "--json"])

        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert "pattern_files_found" in data
        assert "renamed" in data
        assert "dry_run" in data
        assert data["dry_run"] is True

    def test_verbose_output(self, runner, temp_dir):
        """Test verbose output shows individual actions."""
        (temp_dir / "file (1).txt").write_text("copy")

        result = runner.invoke(rename, [str(temp_dir), "--verbose"])

        assert result.exit_code == 0
        assert "Would rename" in result.output or "Would delete" in result.output

    def test_summary_output(self, runner, temp_dir):
        """Test summary output format."""
        result = runner.invoke(rename, [str(temp_dir)])

        assert result.exit_code == 0
        assert "Rename Summary" in result.output
        assert "Mode:" in result.output
        assert "Actions:" in result.output


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_handles_copy_suffix_variants(self, runner, temp_dir):
        """Test different - Copy variants."""
        (temp_dir / "file - Copy.txt").write_text("copy")
        (temp_dir / "doc - Copie.txt").write_text("copie")

        result = runner.invoke(rename, [str(temp_dir), "--execute"])

        assert result.exit_code == 0
        assert (temp_dir / "file.txt").exists()
        assert (temp_dir / "doc.txt").exists()

    def test_skips_inaccessible_files(self, runner, temp_dir):
        """Test graceful handling of inaccessible files."""
        (temp_dir / "file (1).txt").write_text("copy")
        os.chmod(temp_dir / "file (1).txt", 0o000)

        result = runner.invoke(rename, [str(temp_dir), "--execute"])

        # Restore permissions if file still exists
        if (temp_dir / "file (1).txt").exists():
            os.chmod(temp_dir / "file (1).txt", 0o644)

        assert result.exit_code == 0
        # Should skip and not crash

    def test_empty_directory(self, runner, temp_dir):
        """Test behavior on empty directory."""
        result = runner.invoke(rename, [str(temp_dir)])

        assert result.exit_code == 0
        assert "Pattern files found: 0" in result.output

    def test_mixed_patterns(self, runner, temp_dir):
        """Test directory with mixed patterns."""
        (temp_dir / "file.txt").write_text("orig")
        (temp_dir / "file (1).txt").write_text("orig")
        (temp_dir / "file (2).txt").write_text("diff")
        (temp_dir / "doc - Copy.txt").write_text("doccopy")
        (temp_dir / "normal.txt").write_text("normal")

        result = runner.invoke(rename, [str(temp_dir), "--execute"])

        assert result.exit_code == 0
        assert (temp_dir / "file.txt").exists()
        assert (temp_dir / "normal.txt").exists()  # Untouched
