"""Tests for consolidate command and library."""

import os
import pytest
from pathlib import Path
from curate.lib.consolidator import (
    Consolidator,
    ConsolidationPlan,
    ConsolidationResult,
    FILE_TYPE_PRESETS,
)


@pytest.fixture
def sample_source(tmp_path):
    """Create a sample source directory with files."""
    source = tmp_path / "source"
    source.mkdir()

    # Create some test files (make them large enough to pass min_size=100)
    (source / "file1.txt").write_text("Hello, World!" * 10)
    (source / "file2.txt").write_text("Hello, World!" * 10)  # Duplicate
    (source / "file3.txt").write_text("Unique content" * 10)

    # Create subdirectory
    subdir = source / "subdir"
    subdir.mkdir()
    (subdir / "file4.txt").write_text("Another unique file" * 10)

    return source


@pytest.fixture
def sample_target(tmp_path):
    """Create a sample target directory."""
    target = tmp_path / "target"
    target.mkdir()
    return target


@pytest.fixture
def source_with_duplicates(tmp_path):
    """Create source with some files that duplicate target content."""
    # Use a common parent for scanning
    base = tmp_path / "base"
    base.mkdir()

    source = base / "source"
    target = base / "target"
    source.mkdir()
    target.mkdir()

    # Create file in target (already organized)
    (target / "organized.txt").write_text("Shared content" * 20)

    # Create duplicate in source
    (source / "duplicate.txt").write_text("Shared content" * 20)

    # Create unique file in source
    (source / "unique.txt").write_text("Only in source" * 20)

    # Scan from base to find both source and target files
    return base, target, source


class TestConsolidator:
    """Test Consolidator class."""

    def test_source_equals_target_check(self, tmp_path):
        """Test that source == target is rejected."""
        source = tmp_path / "same"
        source.mkdir()

        consolidator = Consolidator(
            source=source,
            target=source,
            file_type="documents",
            dry_run=True,
        )

        assert not consolidator.pre_flight()

    def test_nonexistent_source(self, tmp_path):
        """Test that nonexistent source is rejected."""
        target = tmp_path / "target"
        target.mkdir()

        consolidator = Consolidator(
            source=tmp_path / "nonexistent",
            target=target,
            file_type="documents",
            dry_run=True,
        )

        assert not consolidator.pre_flight()

    def test_scan_source_finds_files(self, sample_source, sample_target):
        """Test scanning source directory."""
        consolidator = Consolidator(
            source=sample_source,
            target=sample_target,
            file_type="documents",
            dry_run=True,
        )

        files = consolidator.scan_and_hash()

        # Should find all .txt files
        assert len(files) == 4
        assert any(f.name == "file1.txt" for f in files.keys())
        assert any(f.name == "file2.txt" for f in files.keys())
        assert any(f.name == "file3.txt" for f in files.keys())
        assert any(f.name == "file4.txt" for f in files.keys())

    def test_scan_source_filters_by_extension(self, sample_source, sample_target):
        """Test that only matching extensions are scanned."""
        # Create a non-matching file
        (sample_source / "file.jpg").write_text("Not a document")

        consolidator = Consolidator(
            source=sample_source,
            target=sample_target,
            file_type="documents",  # Only .txt, .pdf, etc.
            dry_run=True,
        )

        files = consolidator.scan_and_hash()

        # Should not find .jpg
        assert not any(f.suffix == ".jpg" for f in files.keys())

    def test_scan_source_filters_by_min_size(self, sample_source, sample_target):
        """Test minimum file size filter."""
        # Create a tiny file
        (sample_source / "tiny.txt").write_text("x")

        consolidator = Consolidator(
            source=sample_source,
            target=sample_target,
            min_size=100,  # Skip files < 100 bytes
            file_type="documents",
            dry_run=True,
        )

        files = consolidator.scan_and_hash()

        # Should not find tiny file
        assert not any(f.name == "tiny.txt" for f in files.keys())

    def test_duplicate_detection(self, source_with_duplicates):
        """Test that duplicates are detected."""
        base, target, source = source_with_duplicates

        consolidator = Consolidator(
            source=base,  # Scan from base to find both
            target=target,
            file_type="documents",
            dry_run=True,
        )

        files = consolidator.scan_and_hash()
        plan = consolidator.plan(files)

        # Should find 1 duplicate and 1 unique
        assert len(plan.files_to_delete) == 1  # duplicate.txt
        assert len(plan.files_to_move) == 1  # unique.txt
        assert any(f.name == "duplicate.txt" for f in plan.files_to_delete)
        assert any(f.name == "unique.txt" for f in [s for s, _ in plan.files_to_move])

    def test_unique_files_moved_to_staging(self, source_with_duplicates):
        """Test that unique files are staged for moving."""
        base, target, source = source_with_duplicates

        consolidator = Consolidator(
            source=base,
            target=target,
            file_type="documents",
            dry_run=True,
        )

        files = consolidator.scan_and_hash()
        plan = consolidator.plan(files)

        # Unique file should be moved to staging
        assert len(plan.files_to_move) == 1
        src, dest = plan.files_to_move[0]
        assert "_STAGING" in str(dest)
        assert src.name == "unique.txt"

    def test_dry_run_does_not_modify_files(self, source_with_duplicates):
        """Test that dry-run doesn't actually move or delete files."""
        base, target, source = source_with_duplicates

        # Track initial state
        initial_files = set(source.glob("*"))

        consolidator = Consolidator(
            source=base,  # Scan from base to find both source and target
            target=target,
            file_type="documents",
            dry_run=True,  # Dry-run mode
        )

        files = consolidator.scan_and_hash()
        plan = consolidator.plan(files)
        result = consolidator.execute(plan)

        # Files should still exist
        assert (source / "duplicate.txt").exists()
        assert (source / "unique.txt").exists()

        # Result should show what would happen
        assert result.files_deleted >= 1
        assert result.files_moved >= 1

    def test_execute_performs_operations(self, source_with_duplicates):
        """Test that execute mode actually performs operations."""
        base, target, source = source_with_duplicates

        consolidator = Consolidator(
            source=base,  # Scan from base to find both
            target=target,
            file_type="documents",
            dry_run=False,  # Execute mode
        )

        files = consolidator.scan_and_hash()
        plan = consolidator.plan(files)
        result = consolidator.execute(plan)

        # Files should be moved/deleted
        assert not (source / "unique.txt").exists()  # Was moved
        # File is in base/source/, so staging subdir is _from_source
        assert (target / "_STAGING" / "_from_source" / "unique.txt").exists()  # Was staged

        # Duplicate should be deleted
        assert not (source / "duplicate.txt").exists()

    def test_min_size_filter(self, sample_source, sample_target):
        """Test minimum size filtering."""
        # Create tiny file
        (sample_source / "tiny.txt").write_text("x")

        consolidator = Consolidator(
            source=sample_source,
            target=sample_target,
            min_size=100,
            file_type="documents",
            dry_run=True,
        )

        files = consolidator.scan_and_hash()
        plan = consolidator.plan(files)

        # Tiny file should not be in plan
        assert not any(f.name == "tiny.txt" for f in plan.files_to_delete)
        assert not any(f.name == "tiny.txt" for f in [s for s, _ in plan.files_to_move])

    def test_file_type_filtering_documents(self, tmp_path):
        """Test document file type preset."""
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        # Create various file types (make them large enough)
        (source / "doc.txt").write_text("text" * 50)
        (source / "doc.pdf").write_bytes(b"%PDF" + b"x" * 200)
        (source / "photo.jpg").write_bytes(b"JPG" + b"x" * 200)
        (source / "music.mp3").write_bytes(b"MP3" + b"x" * 200)

        consolidator = Consolidator(
            source=source,
            target=target,
            file_type="documents",
            dry_run=True,
        )

        files = consolidator.scan_and_hash()

        # Should only find documents
        assert len(files) == 2
        assert any(f.name == "doc.txt" for f in files.keys())
        assert any(f.name == "doc.pdf" for f in files.keys())
        assert not any(f.name == "photo.jpg" for f in files.keys())
        assert not any(f.name == "music.mp3" for f in files.keys())

    def test_file_type_filtering_pictures(self, tmp_path):
        """Test pictures file type preset."""
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        # Create various file types (make them large enough)
        (source / "doc.txt").write_text("text" * 50)
        (source / "photo.jpg").write_bytes(b"JPG" + b"x" * 200)
        (source / "photo.png").write_bytes(b"PNG" + b"x" * 200)

        consolidator = Consolidator(
            source=source,
            target=target,
            file_type="pictures",
            dry_run=True,
        )

        files = consolidator.scan_and_hash()

        # Should only find pictures
        assert len(files) == 2
        assert any(f.name == "photo.jpg" for f in files.keys())
        assert any(f.name == "photo.png" for f in files.keys())
        assert not any(f.name == "doc.txt" for f in files.keys())

    def test_file_type_all(self, tmp_path):
        """Test 'all' file type includes everything."""
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        # Create various file types (make them large enough)
        (source / "doc.txt").write_text("text" * 50)
        (source / "photo.jpg").write_bytes(b"JPG" + b"x" * 200)
        (source / "music.mp3").write_bytes(b"MP3" + b"x" * 200)

        consolidator = Consolidator(
            source=source,
            target=target,
            file_type="all",
            dry_run=True,
        )

        files = consolidator.scan_and_hash()

        # Should find all files
        assert len(files) == 3

    def test_staging_subdir_generation(self, sample_source, sample_target):
        """Test staging subdirectory naming."""
        consolidator = Consolidator(
            source=sample_source,
            target=sample_target,
            file_type="documents",
            dry_run=True,
        )

        # Test file at root
        root_file = sample_source / "root.txt"
        subdir = consolidator._get_staging_subdir(root_file)
        assert subdir == "_from_root"

        # Test file in subdirectory
        sub_file = sample_source / "subdir" / "file.txt"
        subdir = consolidator._get_staging_subdir(sub_file)
        assert subdir == "_from_subdir"

    def test_skipped_directories(self, tmp_path):
        """Test that certain directories are skipped."""
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        # Create directories that should be skipped
        (source / ".git").mkdir()
        (source / ".git" / "file.txt").write_text("Should be skipped" * 20)

        (source / "node_modules").mkdir()
        (source / "node_modules" / "file.txt").write_text("Should be skipped" * 20)

        # Create normal directory
        (source / "normal").mkdir()
        (source / "normal" / "file.txt").write_text("Should be found" * 20)

        consolidator = Consolidator(
            source=source,
            target=target,
            file_type="documents",
            dry_run=True,
        )

        files = consolidator.scan_and_hash()

        # Should only find file in normal directory
        assert len(files) == 1
        assert any(f.parent.name == "normal" for f in files.keys())

    def test_full_pipeline_run(self, source_with_duplicates):
        """Test complete consolidation pipeline."""
        base, target, source = source_with_duplicates

        consolidator = Consolidator(
            source=base,  # Scan from base to find both
            target=target,
            file_type="documents",
            dry_run=True,
        )

        result = consolidator.run()

        # Result should be valid
        assert isinstance(result, ConsolidationResult)
        assert result.duplicates_found >= 1
        assert result.files_moved >= 1
        assert result.files_deleted >= 1

    def test_result_statistics(self, source_with_duplicates):
        """Test that result tracks statistics correctly."""
        base, target, source = source_with_duplicates

        consolidator = Consolidator(
            source=base,  # Scan from base to find both
            target=target,
            file_type="documents",
            dry_run=True,
        )

        files = consolidator.scan_and_hash()
        plan = consolidator.plan(files)
        result = consolidator.execute(plan)

        # Check statistics
        assert result.files_moved == len(plan.files_to_move)
        assert result.files_deleted == len(plan.files_to_delete)
        assert result.space_organized == plan.total_move_size
        assert result.space_freed == plan.total_delete_size

    def test_collision_handling(self, sample_source, sample_target):
        """Test that file name collisions are handled when staging."""
        # Create a file that would collide in staging
        # by pre-creating the destination
        staging_dir = sample_target / "_STAGING" / "_from_root"
        staging_dir.mkdir(parents=True, exist_ok=True)
        (staging_dir / "collision_test.txt").write_text("already exists" * 20)

        # Now scan and plan - should handle collision
        (sample_source / "collision_test.txt").write_text("new content" * 20)

        consolidator = Consolidator(
            source=sample_source,
            target=sample_target,
            file_type="documents",
            dry_run=False,
        )

        files = consolidator.scan_and_hash()
        plan = consolidator.plan(files)

        # Find the collision_test file in the plan
        collision_file_move = None
        for src, dest in plan.files_to_move:
            if src.name == "collision_test.txt":
                collision_file_move = (src, dest)
                break

        # Should have found the file and handled collision
        assert collision_file_move is not None, "collision_test.txt should be in plan"

        src, dest = collision_file_move
        # Destination should either be the original (if no collision) or have numeric suffix
        # Since we pre-created it, it should have a suffix
        assert dest.name.startswith("collision_test")
        assert dest.name != "collision_test.txt" or not (staging_dir / "collision_test.txt").exists()

    def test_format_size(self):
        """Test size formatting."""
        consolidator = Consolidator(
            source=Path("/fake"),
            target=Path("/fake"),
            file_type="documents",
            dry_run=True,
        )

        assert consolidator._format_size(100) == "100.0 B"
        assert consolidator._format_size(1024) == "1.0 KB"
        assert consolidator._format_size(1024 * 1024) == "1.0 MB"
        assert consolidator._format_size(1024 * 1024 * 1024) == "1.0 GB"


class TestCLI:
    """Test CLI integration."""

    def test_consolidate_command_exists(self):
        """Test that consolidate command is available."""
        from curate.cli import cli
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "consolidate" in result.output

    def test_consolidate_requires_arguments(self):
        """Test that consolidate requires source and target."""
        from curate.cli import cli
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(cli, ["consolidate"])
        assert "Missing argument" in result.output or "usage:" in result.output.lower()

    def test_consolidate_help(self):
        """Test consolidate help text."""
        from curate.cli import cli
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(cli, ["consolidate", "--help"])
        assert "consolidate" in result.output
        assert "SOURCE" in result.output
        assert "TARGET" in result.output
        assert "--file-type" in result.output
        assert "--execute" in result.output


class TestDataStructures:
    """Test data structures."""

    def test_file_info_to_dict(self):
        """Test FileInfo serialization."""
        from curate.lib.consolidator import FileInfo

        info = FileInfo(
            path=Path("/test/file.txt"),
            size=100,
            hash="abc123",
            in_target=False,
        )

        d = info.to_dict()
        assert d["path"] == "/test/file.txt"
        assert d["size"] == 100
        assert d["hash"] == "abc123"
        assert d["in_target"] is False

    def test_consolidation_plan(self):
        """Test ConsolidationPlan."""
        plan = ConsolidationPlan(
            files_to_move=[(Path("/src"), Path("/dst"))],
            files_to_delete=[Path("/del")],
            staging_paths={Path("/src"): Path("/dst")},
            total_move_size=100,
            total_delete_size=50,
        )

        assert len(plan) == 2  # 1 move + 1 delete

    def test_consolidation_result_to_dict(self):
        """Test ConsolidationResult serialization."""
        result = ConsolidationResult(
            files_moved=5,
            files_deleted=3,
            duplicates_found=3,
            space_organized=1000,
            space_freed=500,
            errors=["error1"],
            failed_hash_files=[Path("/failed")],
        )

        d = result.to_dict()
        assert d["files_moved"] == 5
        assert d["files_deleted"] == 3
        assert d["duplicates_found"] == 3
        assert d["space_organized"] == 1000
        assert d["space_freed"] == 500
        assert d["errors"] == ["error1"]

    def test_file_type_presets(self):
        """Test that file type presets are defined."""
        assert "documents" in FILE_TYPE_PRESETS
        assert "music" in FILE_TYPE_PRESETS
        assert "pictures" in FILE_TYPE_PRESETS
        assert "videos" in FILE_TYPE_PRESETS
        assert "email" in FILE_TYPE_PRESETS

        # Check some extensions
        assert ".pdf" in FILE_TYPE_PRESETS["documents"]
        assert ".mp3" in FILE_TYPE_PRESETS["music"]
        assert ".jpg" in FILE_TYPE_PRESETS["pictures"]
        assert ".mp4" in FILE_TYPE_PRESETS["videos"]
