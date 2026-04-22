"""Tests for snapshot command and scanner."""

import json
from pathlib import Path

import pytest

from curate.lib.scanner import Scanner, Snapshot, ExtensionStats, DirStats


class TestScanner:
    """Test Scanner class functionality."""

    def test_scan_small_directory(self, tmp_path: Path) -> None:
        """Test scanning a small directory with known files."""
        # Create test files
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.jpg").write_bytes(b"image data")
        (tmp_path / "file3.pdf").write_bytes(b"pdf content")

        # Create subdirectory with files
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file4.txt").write_text("more content")

        scanner = Scanner(str(tmp_path))
        snapshot = scanner.scan()

        # Verify basic structure
        assert snapshot.path == str(tmp_path)
        assert isinstance(snapshot.timestamp, str)
        assert "total_bytes" in snapshot.disk_usage
        assert snapshot.summary["total_files"] == 4
        assert snapshot.summary["total_dirs"] >= 1

    def test_extension_grouping(self, tmp_path: Path) -> None:
        """Test that files are correctly grouped by extension."""
        # Create files with different extensions
        (tmp_path / "file1.txt").write_text("text")
        (tmp_path / "file2.txt").write_text("text2")
        (tmp_path / "file3.jpg").write_bytes(b"image")
        (tmp_path / "file4.pdf").write_bytes(b"pdf")

        scanner = Scanner(str(tmp_path))
        snapshot = scanner.scan()

        # Check extension grouping
        assert ".txt" in snapshot.by_extension
        assert snapshot.by_extension[".txt"]["count"] == 2

        assert ".jpg" in snapshot.by_extension
        assert snapshot.by_extension[".jpg"]["count"] == 1

        assert ".pdf" in snapshot.by_extension
        assert snapshot.by_extension[".pdf"]["count"] == 1

    def test_top_level_directory_stats(self, tmp_path: Path) -> None:
        """Test that top-level directories are tracked correctly."""
        # Create top-level directories with files
        docs = tmp_path / "Documents"
        docs.mkdir()
        (docs / "file1.txt").write_text("doc1")
        (docs / "file2.txt").write_text("doc2")

        pics = tmp_path / "Pictures"
        pics.mkdir()
        (pics / "photo1.jpg").write_bytes(b"photo")

        # Create nested directory (should not be top-level)
        nested = docs / "nested"
        nested.mkdir()
        (nested / "file3.txt").write_text("nested")

        scanner = Scanner(str(tmp_path))
        snapshot = scanner.scan()

        # Check top-level directories
        assert "Documents" in snapshot.top_level_dirs
        assert snapshot.top_level_dirs["Documents"]["file_count"] == 3  # includes nested

        assert "Pictures" in snapshot.top_level_dirs
        assert snapshot.top_level_dirs["Pictures"]["file_count"] == 1

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Test scanning an empty directory."""
        scanner = Scanner(str(tmp_path))
        snapshot = scanner.scan()

        assert snapshot.summary["total_files"] == 0
        assert snapshot.summary["total_size_bytes"] == 0
        assert len(snapshot.by_extension) == 0
        assert len(snapshot.largest_files) == 0

    def test_quick_scan_skips_largest_files(self, tmp_path: Path) -> None:
        """Test that quick scan does not include largest files."""
        # Create some files
        for i in range(10):
            (tmp_path / f"file{i}.txt").write_text(f"content {i}")

        scanner = Scanner(str(tmp_path))

        # Full scan should include largest files
        full_snapshot = scanner.scan()
        assert len(full_snapshot.largest_files) > 0

        # Quick scan should skip largest files
        quick_snapshot = scanner.quick_scan()
        assert len(quick_snapshot.largest_files) == 0

    def test_snapshot_json_serialization(self, tmp_path: Path) -> None:
        """Test that snapshots can be serialized and deserialized from JSON."""
        # Create test files
        (tmp_path / "file1.txt").write_text("content")
        (tmp_path / "file2.jpg").write_bytes(b"image")

        scanner = Scanner(str(tmp_path))
        original_snapshot = scanner.scan()

        # Serialize to JSON
        json_str = scanner.to_json(original_snapshot)
        assert isinstance(json_str, str)

        # Deserialize from JSON
        restored_snapshot = scanner.from_json(json_str)

        # Verify restored snapshot matches original
        assert restored_snapshot.path == original_snapshot.path
        assert restored_snapshot.timestamp == original_snapshot.timestamp
        assert restored_snapshot.summary == original_snapshot.summary
        assert restored_snapshot.by_extension == original_snapshot.by_extension

    def test_diff_between_snapshots(self, tmp_path: Path) -> None:
        """Test comparing two snapshots to find differences."""
        scanner = Scanner(str(tmp_path))

        # Create initial snapshot
        (tmp_path / "file1.txt").write_text("original")
        (tmp_path / "file2.jpg").write_bytes(b"original image")
        snapshot1 = scanner.scan()

        # Modify directory
        (tmp_path / "file3.pdf").write_bytes(b"new file")
        (tmp_path / "file1.txt").write_text("modified content - much longer")

        # Create new snapshot
        snapshot2 = scanner.scan()

        # Compare
        diff = snapshot2.diff(snapshot1)

        assert diff.files_added >= 1  # At least file3.pdf
        assert diff.path == str(tmp_path)
        assert isinstance(diff.summary, str)
        assert isinstance(diff.new_extensions, dict)

    def test_diff_with_new_extensions(self, tmp_path: Path) -> None:
        """Test that diff detects new file extensions."""
        scanner = Scanner(str(tmp_path))

        # Initial snapshot with .txt files
        (tmp_path / "file1.txt").write_text("text")
        snapshot1 = scanner.scan()

        # Add .pdf files
        (tmp_path / "file2.pdf").write_bytes(b"pdf")
        snapshot2 = scanner.scan()

        # Compare
        diff = snapshot2.diff(snapshot1)

        assert ".pdf" in diff.new_extensions
        assert diff.new_extensions[".pdf"] == 1

    def test_skip_directories(self, tmp_path: Path) -> None:
        """Test that specified directories are skipped during scan."""
        # Create files in different directories
        (tmp_path / "file.txt").write_text("root")

        node_modules = tmp_path / "node_modules"
        node_modules.mkdir()
        (node_modules / "package.json").write_text("{}")
        (node_modules / "index.js").write_text("console.log('test')")

        git = tmp_path / ".git"
        git.mkdir()
        (git / "config").write_text("[core]")

        scanner = Scanner(str(tmp_path))
        snapshot = scanner.scan()

        # node_modules and .git should be skipped
        assert "node_modules" not in snapshot.top_level_dirs
        assert ".git" not in snapshot.top_level_dirs

        # Only root file should be counted
        assert snapshot.summary["total_files"] == 1

    def test_max_samples_limit(self, tmp_path: Path) -> None:
        """Test that sample paths are limited to max_samples."""
        # Create many .txt files
        for i in range(10):
            (tmp_path / f"file{i}.txt").write_text(f"content {i}")

        scanner = Scanner(str(tmp_path), max_samples=3)
        snapshot = scanner.scan()

        # Should only keep 3 sample paths
        assert len(snapshot.by_extension[".txt"]["sample_paths"]) == 3

    def test_largest_files_sorting(self, tmp_path: Path) -> None:
        """Test that largest files are sorted correctly by size."""
        # Create files of different sizes
        (tmp_path / "small.txt").write_text("x")
        (tmp_path / "medium.txt").write_text("x" * 100)
        (tmp_path / "large.txt").write_text("x" * 1000)
        (tmp_path / "huge.txt").write_text("x" * 10000)

        scanner = Scanner(str(tmp_path))
        snapshot = scanner.scan()

        # Check that files are sorted by size (largest first)
        largest_files = snapshot.largest_files
        assert len(largest_files) == 4

        # First file should be the largest
        assert "huge.txt" in largest_files[0]["path"]
        assert largest_files[0]["size_bytes"] == 10000

        # Last file should be the smallest
        assert "small.txt" in largest_files[-1]["path"]
        assert largest_files[-1]["size_bytes"] == 1

    def test_files_without_extension(self, tmp_path: Path) -> None:
        """Test handling of files without extensions."""
        # Create files without extensions
        (tmp_path / "README").write_text("readme content")
        (tmp_path / "Makefile").write_text("make content")

        scanner = Scanner(str(tmp_path))
        snapshot = scanner.scan()

        # Should have empty string extension
        assert "" in snapshot.by_extension
        assert snapshot.by_extension[""]["count"] == 2


class TestSnapshotCommand:
    """Test snapshot Click command integration."""

    def test_snapshot_command_runs(self, tmp_path: Path, runner: any) -> None:
        """Test that the snapshot command runs without errors."""
        # Create test files
        (tmp_path / "test.txt").write_text("content")

        from curate.cli import cli
        result = runner.invoke(cli, ["snapshot", str(tmp_path)])

        assert result.exit_code == 0
        assert "Snapshot:" in result.output
        assert "Files:" in result.output

    def test_snapshot_quick_format(self, tmp_path: Path, runner: any) -> None:
        """Test quick format produces output without largest files."""
        (tmp_path / "file.txt").write_text("content")

        from curate.cli import cli
        result = runner.invoke(cli, ["snapshot", str(tmp_path), "--format", "quick"])

        assert result.exit_code == 0
        assert "Snapshot:" in result.output
        # Quick format should not show largest files section
        assert "Largest Files" not in result.output

    def test_snapshot_json_format(self, tmp_path: Path, runner: any) -> None:
        """Test JSON format produces valid JSON."""
        (tmp_path / "file.txt").write_text("content")

        from curate.cli import cli
        result = runner.invoke(cli, ["snapshot", str(tmp_path), "--format", "json"])

        assert result.exit_code == 0

        # Verify output is valid JSON
        data = json.loads(result.output)
        assert "path" in data
        assert "timestamp" in data
        assert "summary" in data

    def test_snapshot_output_to_file(self, tmp_path: Path, runner: any) -> None:
        """Test saving snapshot to file."""
        (tmp_path / "file.txt").write_text("content")

        output_file = tmp_path / "snapshot.json"

        from curate.cli import cli
        result = runner.invoke(cli, ["snapshot", str(tmp_path), "--format", "json", "--output", str(output_file)])

        assert result.exit_code == 0
        assert output_file.exists()

        # Verify file content is valid JSON
        content = output_file.read_text()
        data = json.loads(content)
        assert "path" in data

    def test_snapshot_diff_mode(self, tmp_path: Path, runner: any) -> None:
        """Test comparing with previous snapshot."""
        # Create initial snapshot
        (tmp_path / "file1.txt").write_text("original")

        output_file = tmp_path / "snapshot1.json"

        from curate.cli import cli
        result1 = runner.invoke(cli, ["snapshot", str(tmp_path), "--format", "json", "--output", str(output_file)])
        assert result1.exit_code == 0

        # Modify directory
        (tmp_path / "file2.txt").write_text("new file")

        # Run diff
        result2 = runner.invoke(cli, ["snapshot", str(tmp_path), "--diff", str(output_file)])

        assert result2.exit_code == 0
        assert "Snapshot Diff" in result2.output or "Summary:" in result2.output


@pytest.fixture
def runner():
    """Create a Click test runner."""
    from click.testing import CliRunner
    from curate.cli import cli

    return CliRunner()
