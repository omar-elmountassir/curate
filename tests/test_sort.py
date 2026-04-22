"""Tests for curate sort command."""

import os
from pathlib import Path

import pytest

from curate.lib.sorter import Sorter, SortResult


class TestSorterDetection:
    """Test auto-detection of file types."""

    def test_detect_documents_directory(self, tmp_path: Path) -> None:
        """Test auto-detection of document directory."""
        # Create test files
        (tmp_path / "test.pdf").touch()
        (tmp_path / "doc.docx").touch()
        (tmp_path / "sheet.xlsx").touch()

        sorter = Sorter(tmp_path, sort_type="auto")
        detected = sorter.detect_type()

        assert detected == "documents"

    def test_detect_music_directory(self, tmp_path: Path) -> None:
        """Test auto-detection of music directory."""
        # Create test files
        (tmp_path / "song.mp3").touch()
        (tmp_path / "track.flac").touch()
        (tmp_path / "audio.wav").touch()

        sorter = Sorter(tmp_path, sort_type="auto")
        detected = sorter.detect_type()

        assert detected == "music"

    def test_detect_pictures_directory(self, tmp_path: Path) -> None:
        """Test auto-detection of pictures directory."""
        # Create test files
        (tmp_path / "photo.jpg").touch()
        (tmp_path / "image.png").touch()
        (tmp_path / "pic.gif").touch()

        sorter = Sorter(tmp_path, sort_type="auto")
        detected = sorter.detect_type()

        assert detected == "pictures"

    def test_detect_videos_directory(self, tmp_path: Path) -> None:
        """Test auto-detection of videos directory."""
        # Create test files
        (tmp_path / "movie.mp4").touch()
        (tmp_path / "clip.avi").touch()
        (tmp_path / "video.mkv").touch()

        sorter = Sorter(tmp_path, sort_type="auto")
        detected = sorter.detect_type()

        assert detected == "videos"

    def test_detect_mixed_directory(self, tmp_path: Path) -> None:
        """Test auto-detection of mixed directory."""
        # Create mixed files (no dominant type)
        (tmp_path / "doc.pdf").touch()
        (tmp_path / "song.mp3").touch()
        (tmp_path / "photo.jpg").touch()
        (tmp_path / "video.mp4").touch()

        sorter = Sorter(tmp_path, sort_type="auto")
        detected = sorter.detect_type()

        assert detected == "mixed"


class TestSorterScanning:
    """Test file scanning and categorization."""

    def test_scan_documents_by_extension(self, tmp_path: Path) -> None:
        """Test document scanning by extension."""
        # Create test files
        (tmp_path / "test.pdf").touch()
        (tmp_path / "doc.docx").touch()
        (tmp_path / "data.xlsx").touch()

        sorter = Sorter(tmp_path, sort_type="documents")
        categories = sorter.scan()

        assert len(categories) > 0
        assert sorter.result.total_files == 3

    def test_scan_music_by_extension(self, tmp_path: Path) -> None:
        """Test music scanning by extension."""
        # Create test files
        (tmp_path / "song.mp3").touch()
        (tmp_path / "track.flac").touch()

        sorter = Sorter(tmp_path, sort_type="music")
        categories = sorter.scan()

        assert len(categories) > 0
        assert sorter.result.total_files == 2

    def test_scan_empty_directory(self, tmp_path: Path) -> None:
        """Test scanning empty directory."""
        sorter = Sorter(tmp_path, sort_type="auto")
        categories = sorter.scan()

        assert len(categories) == 0
        assert sorter.result.total_files == 0


class TestSorterDryRun:
    """Test dry-run mode doesn't modify files."""

    def test_dry_run_doesnt_move_files(self, tmp_path: Path) -> None:
        """Test that dry-run doesn't actually move files."""
        # Create test file
        test_file = tmp_path / "test.pdf"
        test_file.touch()

        # Sort in dry-run mode
        sorter = Sorter(tmp_path, sort_type="documents", dry_run=True)
        result = sorter.sort()

        # File should still exist in original location
        assert test_file.exists()
        assert result.moved_count == 1

    def test_execute_moves_files(self, tmp_path: Path) -> None:
        """Test that execute mode actually moves files."""
        # Create test file
        test_file = tmp_path / "test.pdf"
        test_file.touch()

        # Sort in execute mode
        sorter = Sorter(tmp_path, sort_type="documents", dry_run=False)
        result = sorter.run()

        # File should be moved
        assert not test_file.exists()
        assert result.moved_count == 1


class TestSorterCollisionHandling:
    """Test collision handling for files with same name."""

    def test_collision_handling(self, tmp_path: Path) -> None:
        """Test that colliding files get unique names."""
        # Create source directory with two files with same name
        source = tmp_path / "source"
        source.mkdir()

        # Create subfolder with duplicate file
        subfolder = source / "subfolder"
        subfolder.mkdir()
        (subfolder / "test.pdf").touch()

        # Create another file with same name at root
        (source / "test.pdf").touch()

        # Sort files - both should be moved to same category
        sorter = Sorter(source, sort_type="documents", dry_run=False)
        result = sorter.run()

        # Check that files were moved
        # One should be test.pdf, the other test_1.pdf
        assert (source / "_Unclassified" / "test.pdf").exists()
        assert (source / "_Unclassified" / "test_1.pdf").exists()
        assert result.moved_count == 2


class TestSorterResults:
    """Test SortResult data structure."""

    def test_sort_result_fields(self, tmp_path: Path) -> None:
        """Test that SortResult contains all expected fields."""
        # Create test file
        (tmp_path / "test.pdf").touch()

        sorter = Sorter(tmp_path, sort_type="documents", dry_run=True)
        result = sorter.sort()

        assert result.total_files == 1
        assert result.moved_count == 1
        assert result.skipped_count == 0
        assert isinstance(result.by_category, dict)
        assert isinstance(result.errors, list)
        assert isinstance(result.space_organized, int)


class TestDocumentClassification:
    """Test document folder classification."""

    def test_classify_professional_folder(self, tmp_path: Path) -> None:
        """Test classification of professional folders."""
        # Create folder with professional pattern
        prof_folder = tmp_path / "SOFITEL"
        prof_folder.mkdir()
        (prof_folder / "doc.pdf").touch()

        sorter = Sorter(tmp_path, sort_type="documents")
        categories = sorter.scan()

        # Should be classified as professional
        assert "05_Professionnel" in categories
        assert len(categories["05_Professionnel"]) == 1

    def test_classify_personnel_folder(self, tmp_path: Path) -> None:
        """Test classification of personnel folders."""
        # Create folder with personnel pattern
        pers_folder = tmp_path / "Desktop"
        pers_folder.mkdir()
        (pers_folder / "doc.pdf").touch()

        sorter = Sorter(tmp_path, sort_type="documents")
        categories = sorter.scan()

        # Should be classified as personnel
        assert "07_Personnel" in categories
        assert len(categories["07_Personnel"]) == 1


class TestPictureDateExtraction:
    """Test picture date extraction from filenames."""

    def test_extract_date_from_yyyymmdd(self, tmp_path: Path) -> None:
        """Test extracting date from YYYYMMDD pattern."""
        # Create test file with date pattern
        (tmp_path / "20240115_123456.jpg").touch()

        sorter = Sorter(tmp_path, sort_type="pictures")
        categories = sorter.scan()

        # Should be categorized by year
        assert "2024" in categories
        assert len(categories["2024"]) == 1

    def test_extract_date_from_img_pattern(self, tmp_path: Path) -> None:
        """Test extracting date from IMG_YYYYMMDD pattern."""
        # Create test file with IMG pattern
        (tmp_path / "IMG_20240115_123456.jpg").touch()

        sorter = Sorter(tmp_path, sort_type="pictures")
        categories = sorter.scan()

        # Should be categorized by year
        assert "2024" in categories
        assert len(categories["2024"]) == 1


class TestVideoSourceClassification:
    """Test video source-based classification."""

    def test_classify_dashcam_video(self, tmp_path: Path) -> None:
        """Test classification of dashcam videos."""
        # Create dashcam pattern video
        (tmp_path / "N_20240115_123456.mp4").touch()

        sorter = Sorter(tmp_path, sort_type="videos")
        categories = sorter.scan()

        # Should be classified as dashcam
        assert "Dashcam" in categories
        assert len(categories["Dashcam"]) == 1

    def test_classify_film_source(self, tmp_path: Path) -> None:
        """Test classification of film sources."""
        # Create folder with film source pattern
        film_folder = tmp_path / "_from_MOVIE"
        film_folder.mkdir()
        (film_folder / "movie.mp4").touch()

        sorter = Sorter(tmp_path, sort_type="videos")
        categories = sorter.scan()

        # Should be classified as Films
        assert "Films" in categories
        assert len(categories["Films"]) == 1
