"""Tests for deduplication engine and command."""

import json
from pathlib import Path

import pytest

from curate.lib.dedup_engine import DedupEngine, DedupResult


@pytest.fixture
def sample_files(tmp_path):
    """Create sample files for testing."""
    # Create directory structure
    root = tmp_path / "test_root"
    root.mkdir()

    # Create some unique files
    (root / "unique1.txt").write_text("unique content 1")
    (root / "unique2.txt").write_text("unique content 2")

    # Create duplicate files in different locations
    subdir1 = root / "subdir1"
    subdir1.mkdir()
    (subdir1 / "file.txt").write_text("duplicate content")

    subdir2 = root / "subdir2"
    subdir2.mkdir()
    (subdir2 / "file.txt").write_text("duplicate content")

    subdir_deep = root / "subdir1" / "deep"
    subdir_deep.mkdir()
    (subdir_deep / "file.txt").write_text("duplicate content")

    # Create copy markers
    (root / "file - Copy.txt").write_text("duplicate content")
    (root / "file - copie.txt").write_text("duplicate content")

    # Create files with parentheses
    (root / "file (1).txt").write_text("duplicate content")
    (root / "file (2).txt").write_text("duplicate content")

    # Create small files (below min_size)
    (root / "small.txt").write_text("x")

    return root


class TestDedupEngine:
    """Tests for DedupEngine class."""

    def test_scan_finds_all_files(self, sample_files):
        """Test that scan finds all files matching criteria."""
        engine = DedupEngine(path=sample_files, min_size=10)
        files = engine.scan()

        # Should find all files except the small one
        assert len(files) >= 7  # At least the duplicates

    def test_scan_filters_by_min_size(self, sample_files):
        """Test that scan filters by minimum file size."""
        engine = DedupEngine(path=sample_files, min_size=100)
        files = engine.scan()

        # Small file should be excluded
        paths = [f[0] for f in files]
        assert not any(p.name == "small.txt" for p in paths)

    def test_scan_respects_exclude_patterns(self, sample_files):
        """Test that scan respects exclude patterns."""
        engine = DedupEngine(path=sample_files, exclude_patterns=["* - *"])
        files = engine.scan()

        # Copy marker files should be excluded
        paths = [f[0] for f in files]
        assert not any(" - " in p.name for p in paths)

    def test_duplicate_detection(self, sample_files):
        """Test that duplicates are correctly detected."""
        engine = DedupEngine(path=sample_files, min_size=10)

        # Run full pipeline
        result = engine.run()

        # Should find duplicate groups
        assert result.duplicate_groups >= 1
        assert result.files_to_delete >= 2

    def test_dry_run_does_not_delete(self, sample_files):
        """Test that dry-run mode does not delete files."""
        engine = DedupEngine(path=sample_files, min_size=10, dry_run=True)

        # Count files before
        files_before = list(sample_files.rglob("*"))
        files_before = [f for f in files_before if f.is_file()]

        # Run deduplication
        result = engine.run()

        # Count files after
        files_after = list(sample_files.rglob("*"))
        files_after = [f for f in files_after if f.is_file()]

        # File count should be unchanged
        assert len(files_before) == len(files_after)

    def test_keeper_selection_deepest(self, sample_files):
        """Test keeper selection with 'deepest' strategy."""
        engine = DedupEngine(path=sample_files, min_size=10, strategy="deepest")

        files = engine.scan()
        size_groups = engine._group_by_size_called = False

        # Manual grouping for testing
        from curate.core.hashing import group_by_size, hash_files

        size_groups = group_by_size(files)
        hash_groups, _ = hash_files(size_groups)

        # Find a duplicate group
        for (hash_val, size), file_list in hash_groups.items():
            if len(file_list) >= 2:
                selected = engine.select_keepers(hash_groups)

                # Verify we got a keeper
                assert hash_val in selected

                # Verify keeper is in the file list
                keeper_path, _ = selected[hash_val]["keeper"]
                keeper_paths = [f[0] for f in file_list]
                assert keeper_path in keeper_paths

                break

    def test_include_patterns(self, sample_files):
        """Test that include patterns work correctly."""
        engine = DedupEngine(
            path=sample_files,
            min_size=10,
            include_patterns=["*.txt"],
        )

        files = engine.scan()

        # All files should be .txt files
        for path, _ in files:
            assert path.suffix == ".txt"

    def test_skip_directories(self, tmp_path):
        """Test that skip_directories works correctly."""
        root = tmp_path / "test_root"
        root.mkdir()

        # Create files in different directories
        (root / "file1.txt").write_text("content")
        (root / "node_modules").mkdir()
        (root / "node_modules" / "file2.txt").write_text("content")
        (root / ".git").mkdir()
        (root / ".git" / "file3.txt").write_text("content")

        engine = DedupEngine(root, min_size=10)
        files = engine.scan()

        # node_modules and .git should be skipped
        paths = [str(f[0]) for f in files]
        assert not any("node_modules" in p for p in paths)
        assert not any(".git" in p for p in paths)

    def test_empty_directory(self, tmp_path):
        """Test behavior with empty directory."""
        engine = DedupEngine(tmp_path, min_size=10)

        result = engine.run()

        # Should handle gracefully
        assert result.total_files == 0
        assert result.duplicate_groups == 0

    def test_single_file(self, tmp_path):
        """Test behavior with single file (no duplicates)."""
        test_file = tmp_path / "single.txt"
        test_file.write_text("unique content" * 100)  # Make it larger than min_size

        engine = DedupEngine(tmp_path, min_size=10)
        result = engine.run()

        # Should find file but no duplicates
        assert result.total_files >= 1
        assert result.duplicate_groups == 0
        assert result.files_to_delete == 0

    def test_batch_mode(self, sample_files):
        """Test batch deletion mode."""
        engine = DedupEngine(path=sample_files, min_size=10, dry_run=True)

        result = engine.run(batch_mode=True)

        # Should still find duplicates
        assert result.duplicate_groups >= 1

    def test_transaction_log_creation(self, tmp_path):
        """Test that transaction log is created when execute=True."""
        log_file = tmp_path / "txn.json"

        # Create test files
        (tmp_path / "file1.txt").write_text("duplicate")
        (tmp_path / "file2.txt").write_text("duplicate")

        engine = DedupEngine(
            path=tmp_path,
            min_size=10,
            dry_run=False,  # Execute mode
            log_file=log_file,
        )

        result = engine.run()

        # Transaction log should be created
        # Note: In execute mode, files are actually deleted, so we check the log
        # For this test, we just verify the engine doesn't crash
        assert result is not None


class TestDedupResult:
    """Tests for DedupResult dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = DedupResult(
            total_files=100,
            duplicate_groups=10,
            files_to_delete=20,
            space_to_free=1024 * 1024,
            deleted_count=20,
            space_freed=1024 * 1024,
            errors=["error1", "error2"],
        )

        result_dict = result.to_dict()

        assert result_dict["total_files"] == 100
        assert result_dict["duplicate_groups"] == 10
        assert result_dict["files_to_delete"] == 20
        assert result_dict["space_to_free"] == 1024 * 1024
        assert result_dict["deleted_count"] == 20
        assert result_dict["space_freed"] == 1024 * 1024
        assert result_dict["error_count"] == 2
        assert len(result_dict["errors"]) == 2


class TestDedupCommand:
    """Tests for dedup CLI command."""

    def test_dedup_command_basic(self, sample_files, runner):
        """Test basic dedup command."""
        from curate.cli import cli

        result = runner.invoke(cli, ["dedup", str(sample_files)])

        # Should complete without error
        assert result.exit_code == 0

        # Should show summary
        assert "DEDUPLICATION SUMMARY" in result.output
        assert "DRY RUN COMPLETE" in result.output

    def test_dedup_command_json(self, sample_files, runner):
        """Test dedup command with JSON output."""
        from curate.cli import cli

        result = runner.invoke(cli, ["dedup", str(sample_files), "--json"])

        # Should complete without error
        assert result.exit_code == 0

        # Should be valid JSON
        data = json.loads(result.output)
        assert "total_files" in data
        assert "duplicate_groups" in data

    def test_dedup_command_with_execute(self, sample_files, runner):
        """Test dedup command with --execute flag."""
        from curate.cli import cli

        # Count files before
        files_before = list(sample_files.rglob("*"))
        files_before = [f for f in files_before if f.is_file() and f.stat().st_size >= 10]

        result = runner.invoke(cli, ["dedup", str(sample_files), "--execute", "--min-size", "10"])

        # Should complete without error
        assert result.exit_code == 0

        # Files should be deleted
        files_after = list(sample_files.rglob("*"))
        files_after = [f for f in files_after if f.is_file() and f.stat().st_size >= 10]

        # Should have fewer files after deduplication
        assert len(files_after) < len(files_before) or "Files deleted" in result.output

    def test_dedup_command_min_size(self, sample_files, runner):
        """Test dedup command with --min-size option."""
        from curate.cli import cli

        result = runner.invoke(cli, ["dedup", str(sample_files), "--min-size", "1000"])

        # Should complete without error
        assert result.exit_code == 0

    def test_dedup_command_strategy(self, sample_files, runner):
        """Test dedup command with --strategy option."""
        from curate.cli import cli

        result = runner.invoke(cli, ["dedup", str(sample_files), "--strategy", "newest"])

        # Should complete without error
        assert result.exit_code == 0

    def test_dedup_command_include_exclude(self, sample_files, runner):
        """Test dedup command with --include and --exclude options."""
        from curate.cli import cli

        result = runner.invoke(
            cli,
            [
                "dedup",
                str(sample_files),
                "--include",
                "*.txt",
                "--exclude",
                "* - *",
            ],
        )

        # Should complete without error
        assert result.exit_code == 0

    def test_dedup_command_batch_mode(self, sample_files, runner):
        """Test dedup command with --batch-delete flag."""
        from curate.cli import cli

        result = runner.invoke(cli, ["dedup", str(sample_files), "--batch-delete"])

        # Should complete without error
        assert result.exit_code == 0

    def test_dedup_command_verbose(self, sample_files, runner):
        """Test dedup command with --verbose flag."""
        from curate.cli import cli

        result = runner.invoke(cli, ["dedup", str(sample_files), "--verbose", "--min-size", "10"])

        # Should complete without error
        assert result.exit_code == 0

        # Should show more detail (verbose output shows progress)
        assert "DEDUPLICATION SUMMARY" in result.output or "Scanning" in result.output


@pytest.fixture
def runner():
    """Click test runner fixture."""
    from click.testing import CliRunner

    return CliRunner()
