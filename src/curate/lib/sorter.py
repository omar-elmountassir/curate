"""Unified file sorter with auto-detection."""

import os
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple

try:
    from mutagen.easyid3 import EasyID3
    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC
    from mutagen.mp4 import MP4
    from mutagen.asf import ASF
    from mutagen.oggvorbis import OggVorbis
    from mutagen.wavpack import WavPack
    from mutagen.aiff import AIFF
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

try:
    from PIL import Image
    from PIL.ExifTags import TAGS
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

from curate.core.safety import collision_path, safe_move


@dataclass
class SortResult:
    """Result of a sorting operation."""
    total_files: int = 0
    by_category: Dict[str, int] = field(default_factory=dict)
    moved_count: int = 0
    skipped_count: int = 0
    space_organized: int = 0  # bytes
    errors: List[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        """Add an error to the result."""
        self.errors.append(error)


class Sorter:
    """
    Unified file sorter with auto-detection.

    Supports sorting documents, music, pictures, and videos.
    Auto-detects file type by scanning extension distribution.
    """

    # Extension mappings
    DOCUMENT_EXTS = {
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.txt', '.rtf', '.csv', '.odt', '.ods', '.odp'
    }
    MUSIC_EXTS = {
        '.mp3', '.flac', '.wav', '.aac', '.ogg', '.wma', '.m4a', '.aiff', '.alac'
    }
    PICTURE_EXTS = {
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.raw',
        '.psd', '.ai', '.heic', '.heif', '.cr2', '.nef', '.orf', '.sr2', '.dng'
    }
    VIDEO_EXTS = {
        '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.3gp'
    }

    # Document classification patterns
    PROFESSIONNEL_PATTERNS = [
        "sofitel", "presentation rh", "sem", "thiercelin", "vivawere",
        "budget", "ceg", "fiscalite", "fiscalité"
    ]
    PERSONNEL_PATTERNS = [
        "desktop", "downloads", "mes documents", "omar", "nm", "divers",
        "a_trier", "documents"
    ]
    RESSOURCES_PATTERNS = [
        "pdf", "zips", "a_renommer", "onedrive"
    ]

    # Video source patterns
    DASHCAM_PATTERN = re.compile(r'^N_\d{8}_\d{6}\.mp4$', re.IGNORECASE)

    def __init__(
        self,
        path: str | Path,
        sort_type: str = "auto",
        staging: Optional[str | Path] = None,
        dry_run: bool = True,
        log_file: Optional[str | Path] = None,
    ) -> None:
        """
        Initialize sorter.

        Args:
            path: Root path to sort
            sort_type: Type of sort (auto, documents, music, pictures, videos)
            staging: Staging directory for sorted files (default: path/_STAGING)
            dry_run: If True, simulate moves without executing
            log_file: Optional log file path
        """
        self.path = Path(path)
        self.sort_type = sort_type
        self.staging = Path(staging) if staging else self.path / "_STAGING"
        self.dry_run = dry_run
        self.log_file = Path(log_file) if log_file else None

        self.result = SortResult()

    def detect_type(self) -> str:
        """
        Auto-detect file type by scanning extension distribution.

        Returns:
            Detected type: 'documents', 'music', 'pictures', 'videos', or 'mixed'
        """
        ext_counts = {
            'documents': 0,
            'music': 0,
            'pictures': 0,
            'videos': 0,
        }

        # Scan files
        for root, _, files in os.walk(self.path):
            for filename in files:
                ext = Path(filename).suffix.lower()
                if ext in self.DOCUMENT_EXTS:
                    ext_counts['documents'] += 1
                elif ext in self.MUSIC_EXTS:
                    ext_counts['music'] += 1
                elif ext in self.PICTURE_EXTS:
                    ext_counts['pictures'] += 1
                elif ext in self.VIDEO_EXTS:
                    ext_counts['videos'] += 1

        # Find dominant type
        total = sum(ext_counts.values())
        if total == 0:
            return 'mixed'

        # Check if one type dominates (>80%)
        for file_type, count in ext_counts.items():
            if count / total > 0.8:
                return file_type

        return 'mixed'

    def scan(self) -> Dict[str, List[Path]]:
        """
        Scan directory and categorize files.

        Returns:
            Dictionary mapping category to list of file paths
        """
        detected_type = self.sort_type
        if detected_type == "auto":
            detected_type = self.detect_type()

        categories = {}

        if detected_type == "documents":
            categories = self._scan_documents()
        elif detected_type == "music":
            categories = self._scan_music()
        elif detected_type == "pictures":
            categories = self._scan_pictures()
        elif detected_type == "videos":
            categories = self._scan_videos()
        else:  # mixed
            # Categorize each file individually
            categories = self._scan_mixed()

        return categories

    def _scan_documents(self) -> Dict[str, List[Path]]:
        """Scan documents using heuristic classification."""
        categories = {
            '01_Administratif': [],
            '02_Finances_et_Comptabilite': [],
            '03_Immobilier_et_Proprietes': [],
            '04_Sante_et_Social': [],
            '05_Professionnel': [],
            '06_Ressources_et_Documentation': [],
            '07_Personnel': [],
            '_Unclassified': [],
        }

        for root, dirs, files in os.walk(self.path):
            # Get top-level folder name for classification
            rel_path = os.path.relpath(root, self.path)
            if rel_path == '.':
                top_folder = ''
            else:
                top_folder = rel_path.split(os.sep)[0]

            category = self._classify_document_folder(top_folder)

            for filename in files:
                ext = Path(filename).suffix.lower()
                if ext in self.DOCUMENT_EXTS or ext == '':
                    file_path = Path(root) / filename
                    categories[category].append(file_path)
                    self.result.total_files += 1

        # Remove empty categories
        return {k: v for k, v in categories.items() if v}

    def _classify_document_folder(self, folder_name: str) -> str:
        """Classify document folder into category."""
        folder_lower = folder_name.lower()

        for pattern in self.PROFESSIONNEL_PATTERNS:
            if pattern in folder_lower:
                return '05_Professionnel'

        for pattern in self.PERSONNEL_PATTERNS:
            if pattern in folder_lower:
                return '07_Personnel'

        for pattern in self.RESSOURCES_PATTERNS:
            if pattern in folder_lower:
                return '06_Ressources_et_Documentation'

        # Check for numeric folders
        if folder_name.startswith("_from_") and folder_name[6:].isdigit():
            return '07_Personnel'

        return '_Unclassified'

    def _scan_music(self) -> Dict[str, List[Path]]:
        """Scan music files for metadata-based sorting."""
        categories = {
            '_Unknown': [],
            '_Various': [],
        }

        for root, _, files in os.walk(self.path):
            for filename in files:
                ext = Path(filename).suffix.lower()
                if ext in self.MUSIC_EXTS:
                    file_path = Path(root) / filename
                    self.result.total_files += 1

                    # Extract artist from metadata
                    if MUTAGEN_AVAILABLE:
                        artist = self._get_music_artist(file_path)
                    else:
                        artist = None

                    if artist:
                        # Normalize artist name
                        artist_display = artist.replace('/', '_').replace('\\', '_')
                        if artist_display not in categories:
                            categories[artist_display] = []
                        categories[artist_display].append(file_path)
                    else:
                        # Check parent folder for classification
                        parent_name = file_path.parent.name
                        if parent_name.startswith("_from_"):
                            category_name = parent_name[6:].title()
                            category_key = f'_Various/{category_name}'
                            if category_key not in categories:
                                categories[category_key] = []
                            categories[category_key].append(file_path)
                        else:
                            categories['_Unknown'].append(file_path)

        # Remove empty categories
        return {k: v for k, v in categories.items() if v}

    def _get_music_artist(self, file_path: Path) -> Optional[str]:
        """Extract artist from audio file metadata."""
        if not MUTAGEN_AVAILABLE:
            return None

        try:
            suffix = file_path.suffix.lower()

            if suffix == '.mp3':
                audio = MP3(file_path, ID3=EasyID3)
                if 'artist' in audio:
                    return str(audio['artist'][0])
            elif suffix == '.flac':
                audio = FLAC(file_path)
                if 'artist' in audio:
                    return str(audio['artist'][0])
            elif suffix in {'.m4a', '.aac', '.alac'}:
                audio = MP4(file_path)
                if '\xa9ART' in audio:
                    return str(audio['\xa9ART'][0])
            elif suffix == '.wma':
                audio = ASF(file_path)
                if 'Author' in audio:
                    return str(audio['Author'][0])
            elif suffix == '.ogg':
                audio = OggVorbis(file_path)
                if 'artist' in audio:
                    return str(audio['artist'][0])
            elif suffix == '.wav':
                audio = WavPack(file_path)
                if 'artist' in audio:
                    return str(audio['artist'][0])
            elif suffix == '.aiff':
                audio = AIFF(file_path)
                if 'artist' in audio:
                    return str(audio['artist'][0])
        except Exception:
            pass

        return None

    def _normalize_name(self, name: str) -> str:
        """Normalize name for comparison: strip, lowercase, remove accents."""
        if not name:
            return ""
        name = name.strip()
        name = unicodedata.normalize('NFD', name)
        name = ''.join(c for c in name if unicodedata.category(c) != 'Mn')
        return name.lower()

    def _scan_pictures(self) -> Dict[str, List[Path]]:
        """Scan pictures using EXIF-based sorting."""
        categories = {
            '_Design': [],
            '_Undated': [],
            '_Misc': [],
        }

        for root, _, files in os.walk(self.path):
            for filename in files:
                ext = Path(filename).suffix.lower()
                file_path = Path(root) / filename

                # Design files
                if ext in {'.psd', '.psb', '.ai', '.indd', '.svg'}:
                    categories['_Design'].append(file_path)
                    self.result.total_files += 1
                    continue

                # Image files
                if ext in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
                           '.webp', '.heic', '.heif', '.raw', '.cr2', '.nef', '.orf', '.sr2', '.dng'}:
                    self.result.total_files += 1

                    # Try EXIF first
                    if PILLOW_AVAILABLE:
                        year = self._get_exif_year(file_path)
                    else:
                        year = None

                    if not year:
                        year = self._get_year_from_filename(file_path)

                    if year:
                        year_str = str(year)
                        if year_str not in categories:
                            categories[year_str] = []
                        categories[year_str].append(file_path)
                    else:
                        categories['_Undated'].append(file_path)

        # Remove empty categories
        return {k: v for k, v in categories.items() if v}

    def _get_exif_year(self, file_path: Path) -> Optional[int]:
        """Extract year from EXIF data using PIL."""
        if not PILLOW_AVAILABLE:
            return None

        try:
            with Image.open(file_path) as img:
                exif = img._getexif()
                if exif is None:
                    return None

                # Look for DateTimeOriginal (tag 36867) or DateTime (tag 306)
                for tag_id in [36867, 306]:
                    if tag_id in exif:
                        date_str = exif[tag_id]
                        match = re.match(r'(\d{4}):(\d{2}):(\d{2})', str(date_str))
                        if match:
                            return int(match.group(1))
        except Exception:
            pass

        return None

    def _get_year_from_filename(self, file_path: Path) -> Optional[int]:
        """Extract year from filename patterns."""
        filename = file_path.name

        # Pattern 1: YYYYMMDD at start
        match = re.match(r'(\d{4})\d{4}', filename)
        if match:
            year = int(match.group(1))
            if 1990 <= year <= 2030:
                return year

        # Pattern 2: IMG_YYYYMMDD or VID_YYYYMMDD
        match = re.match(r'(?:IMG|VID|PHOTO)_(\d{4})\d{4}', filename, re.IGNORECASE)
        if match:
            year = int(match.group(1))
            if 1990 <= year <= 2030:
                return year

        # Pattern 3: YYYY-MM-DD or YYYY_MM_DD
        match = re.search(r'(\d{4})[-_]\d{2}[-_]\d{2}', filename)
        if match:
            year = int(match.group(1))
            if 1990 <= year <= 2030:
                return year

        return None

    def _scan_videos(self) -> Dict[str, List[Path]]:
        """Scan videos using source-based classification."""
        categories = {
            'Films': [],
            'WhatsApp Video': [],
            'Dashcam': [],
            'Famille': [],
            '_Misc': [],
        }

        for root, dirs, files in os.walk(self.path):
            # Get source folder name
            rel_path = os.path.relpath(root, self.path)
            if rel_path == '.':
                source_name = ''
            else:
                source_name = rel_path.split(os.sep)[0]

            for filename in files:
                ext = Path(filename).suffix.lower()
                if ext in self.VIDEO_EXTS:
                    file_path = Path(root) / filename
                    self.result.total_files += 1

                    # Check dashcam pattern first
                    if self.DASHCAM_PATTERN.match(filename):
                        categories['Dashcam'].append(file_path)
                        continue

                    # Classify by source
                    category = self._classify_video_source(source_name, file_path)
                    categories[category].append(file_path)

        # Remove empty categories
        return {k: v for k, v in categories.items() if v}

    def _classify_video_source(self, source_name: str, file_path: Path) -> str:
        """Classify video by source folder."""
        # Film sources
        film_sources = {
            '_from_movie', '_from_films', '_from_movies', '_from_film',
            '_from_ro', '_from_f03'
        }
        if source_name.lower() in film_sources:
            return 'Films'

        # WhatsApp
        if source_name.lower() == '_from_whatsapp video':
            return 'WhatsApp Video'

        # Famille sources
        famille_sources = {
            '_from_pellicule', '_from_videos', '_from_vidéos',
            '_from_home videos', '_from_attachments', '_from_sent',
        }
        if source_name.lower() in famille_sources:
            return 'Famille'

        # Default
        return '_Misc'

    def _scan_mixed(self) -> Dict[str, List[Path]]:
        """Scan mixed content by individual file type."""
        categories = {}

        for root, _, files in os.walk(self.path):
            for filename in files:
                ext = Path(filename).suffix.lower()
                file_path = Path(root) / filename

                if ext in self.DOCUMENT_EXTS:
                    category = 'Documents'
                elif ext in self.MUSIC_EXTS:
                    category = 'Music'
                elif ext in self.PICTURE_EXTS:
                    category = 'Pictures'
                elif ext in self.VIDEO_EXTS:
                    category = 'Videos'
                else:
                    category = '_Misc'

                if category not in categories:
                    categories[category] = []
                categories[category].append(file_path)
                self.result.total_files += 1

        return categories

    def sort(self) -> SortResult:
        """
        Execute sorting operation.

        Returns:
            SortResult with statistics
        """
        categories = self.scan()

        # Sort each category
        for category, files in categories.items():
            self.result.by_category[category] = len(files)

            # Create target directory
            target_dir = self.path / category
            if not self.dry_run:
                target_dir.mkdir(parents=True, exist_ok=True)

            # Move files
            for file_path in files:
                try:
                    # Generate collision-free path
                    target_path = collision_path(target_dir / file_path.name)

                    # Get file size before moving
                    size = file_path.stat().st_size

                    # Move file
                    if safe_move(file_path, target_path, dry_run=self.dry_run):
                        self.result.moved_count += 1
                        self.result.space_organized += size
                    else:
                        self.result.skipped_count += 1
                        self.result.add_error(f"Failed to move {file_path}")

                except Exception as e:
                    self.result.skipped_count += 1
                    self.result.add_error(f"Error moving {file_path}: {e}")

        return self.result

    def run(self) -> SortResult:
        """
        Run full sorting pipeline.

        Returns:
            SortResult with statistics
        """
        return self.sort()
