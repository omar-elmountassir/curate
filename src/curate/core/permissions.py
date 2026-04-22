"""Cross-platform permission fixing utilities."""

import subprocess
from pathlib import Path


def fix_permissions(
    path: Path, uid: Optional[int] = None, gid: Optional[int] = None, recursive: bool = True
) -> bool:
    """
    Fix file ownership and permissions.

    Args:
        path: Path to fix
        uid: User ID (default: None = no change)
        gid: Group ID (default: None = no change)
        recursive: Apply recursively to directories

    Returns:
        True if successful, False on error
    """
    try:
        # Build chown command
        if uid is not None and gid is not None:
            ownership = f"{uid}:{gid}"
        elif uid is not None:
            ownership = str(uid)
        elif gid is not None:
            ownership = f":{gid}"
        else:
            # No ownership change needed
            pass

        cmd = ["chown"]
        if recursive:
            cmd.append("-R")

        if uid is not None or gid is not None:
            cmd.extend([ownership, str(path)])

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return False

        # Fix permissions - readable/writable by owner, readable by others
        perm_cmd = ["chmod"]
        if recursive:
            perm_cmd.append("-R")
        perm_cmd.extend(["u+rwX,go+rX", str(path)])

        result = subprocess.run(perm_cmd, capture_output=True, text=True)
        return result.returncode == 0

    except Exception:
        return False


def fix_permissions_ntfs(path: Path, uid: int = 1000, gid: int = 1000) -> bool:
    """
    Fix permissions for NTFS3 mounts.

    NTFS3 filesystems often have permission issues; this applies
    standard ownership fixes for external drives.

    Args:
        path: Path to fix
        uid: User ID (default: 1000, typical first user)
        gid: Group ID (default: 1000, typical first user)

    Returns:
        True if successful, False on error
    """
    return fix_permissions(path, uid=uid, gid=gid, recursive=True)
