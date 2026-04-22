"""Core utilities for file curation operations."""

from curate.core.hashing import (
    file_hash,
    file_size,
    files_match_hash,
    group_by_size,
    hash_files,
)
from curate.core.transaction import TransactionLog
from curate.core.progress import ProgressTracker
from curate.core.safety import (
    DryRunContext,
    pre_flight_check,
    collision_path,
    safe_move,
    safe_delete,
)
from curate.core.permissions import fix_permissions, fix_permissions_ntfs

__all__ = [
    # Hashing
    "file_hash",
    "file_size",
    "files_match_hash",
    "group_by_size",
    "hash_files",
    # Transaction
    "TransactionLog",
    # Progress
    "ProgressTracker",
    # Safety
    "DryRunContext",
    "pre_flight_check",
    "collision_path",
    "safe_move",
    "safe_delete",
    # Permissions
    "fix_permissions",
    "fix_permissions_ntfs",
]
