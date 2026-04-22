"""File hashing utilities for deduplication."""

from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set
from collections import defaultdict
import hashlib


# Default chunk size for hashing (64 KB)
CHUNK_SIZE = 65536


def file_hash(path: Path, chunk_size: int = CHUNK_SIZE) -> Optional[str]:
    """
    Compute MD5 hash of a file.

    Args:
        path: Path to file
        chunk_size: Read chunk size in bytes

    Returns:
        MD5 hex digest, or None if file cannot be read
    """
    md5 = hashlib.md5()

    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                md5.update(chunk)

        return md5.hexdigest()

    except (OSError, PermissionError) as e:
        # Caller should handle the None return
        return None


def file_size(path: Path) -> Optional[int]:
    """
    Get file size in bytes.

    Args:
        path: Path to file

    Returns:
        Size in bytes, or None if file cannot be accessed
    """
    try:
        return path.stat().st_size
    except (OSError, PermissionError):
        return None


def files_match_hash(path1: Path, path2: Path, chunk_size: int = CHUNK_SIZE) -> Optional[bool]:
    """
    Compare two files by hash.

    Args:
        path1: First file path
        path2: Second file path
        chunk_size: Read chunk size in bytes

    Returns:
        True if hashes match, False if they differ, None if either file cannot be read
    """
    hash1 = file_hash(path1, chunk_size)
    hash2 = file_hash(path2, chunk_size)

    if hash1 is None or hash2 is None:
        return None

    return hash1 == hash2


def group_by_size(files: List[Tuple[Path, int]]) -> Dict[int, List[Tuple[Path, int]]]:
    """
    Group files by size (fast pre-filter for deduplication).

    Only files with identical sizes can be duplicates, so this allows us to
    skip expensive hashing for files with unique sizes.

    Args:
        files: List of (path, size) tuples

    Returns:
        Dictionary mapping size to list of (path, size) tuples
    """
    size_groups = defaultdict(list)

    for file_path, size in files:
        size_groups[size].append((file_path, size))

    return size_groups


def hash_files(
    size_groups: Dict[int, List[Tuple[Path, int]]],
    progress_callback=None
) -> Tuple[Dict[Tuple[str, int], List[Tuple[Path, int]]], Set[Path]]:
    """
    Hash files with same size to find duplicates.

    Only hashes files within size groups that have 2+ members, since
    files with unique sizes cannot be duplicates.

    Args:
        size_groups: Dictionary from group_by_size()
        progress_callback: Optional callback(count, total) for progress updates

    Returns:
        Tuple of:
        - hash_groups: dict mapping (hash, size) to list of (path, size) tuples
        - failed_files: set of files that failed to hash (excluded from groups)
    """
    hash_groups = defaultdict(list)
    failed_files = set()

    # Find groups with 2+ files
    potential_dup_groups = {
        size: file_list
        for size, file_list in size_groups.items()
        if len(file_list) >= 2
    }

    total_to_hash = sum(len(file_list) for file_list in potential_dup_groups.values())
    hashed_count = 0

    for size, file_list in sorted(potential_dup_groups.items()):
        for file_path, file_size in file_list:
            md5_hash = file_hash(file_path)

            # Exclude failed hashes from all groups
            if md5_hash is None:
                failed_files.add(file_path)
            else:
                hash_groups[(md5_hash, size)].append((file_path, file_size))

            hashed_count += 1

            # Progress callback
            if progress_callback:
                progress_callback(hashed_count, total_to_hash)

    return hash_groups, failed_files
