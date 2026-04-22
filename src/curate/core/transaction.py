"""Transaction logging for atomic file operations."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List


class TransactionLog:
    """
    Transaction log for atomic file operations.

    Records every operation before it happens, enabling recovery on interruption.
    Supports idempotent operations by tracking status and expected file sizes.
    """

    def __init__(self, log_path: Path) -> None:
        """
        Initialize transaction log.

        Args:
            log_path: Path to transaction log file (JSON)
        """
        self.log_path = log_path
        self.entries: List[Dict[str, Any]] = []

    def log_operation(
        self,
        op_type: str,
        source: Path,
        dest: Optional[Path] = None,
        hash_val: Optional[str] = None,
        expected_size: Optional[int] = None,
    ) -> int:
        """
        Log a file operation before execution.

        Args:
            op_type: Operation type (delete, move, copy, etc.)
            source: Source file path
            dest: Destination path (for move/copy operations)
            hash_val: File hash for verification
            expected_size: Expected file size for idempotency check

        Returns:
            Index of the added entry
        """
        entry = {
            "op_type": op_type,
            "source": str(source),
            "status": "pending",
        }

        if dest:
            entry["dest"] = str(dest)
        if hash_val:
            entry["hash"] = hash_val
        if expected_size is not None:
            entry["expected_size"] = expected_size

        self.entries.append(entry)
        self._write()

        return len(self.entries) - 1

    def mark_completed(self, index: int) -> None:
        """
        Mark an operation as completed successfully.

        Args:
            index: Entry index from log_operation()
        """
        if 0 <= index < len(self.entries):
            self.entries[index]["status"] = "done"
            self._write()

    def mark_failed(self, index: int, reason: str = "failed") -> None:
        """
        Mark an operation as failed.

        Args:
            index: Entry index from log_operation()
            reason: Failure reason (becomes status value)
        """
        if 0 <= index < len(self.entries):
            self.entries[index]["status"] = reason
            self._write()

    def update_status(self, index: int, status: str) -> None:
        """
        Update status of an entry.

        Args:
            index: Entry index from log_operation()
            status: New status value
        """
        if 0 <= index < len(self.entries):
            self.entries[index]["status"] = status
            self._write()

    def _write(self) -> None:
        """Write transaction log to disk."""
        try:
            with open(self.log_path, "w") as f:
                json.dump(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "entries": self.entries,
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            # Log write failures - caller should handle
            raise IOError(f"Failed to write transaction log: {e}")

    def recover(self) -> List[Dict[str, Any]]:
        """
        Read log and find incomplete operations for recovery.

        Returns:
            List of entries with status != "done"
        """
        incomplete = [e for e in self.entries if e.get("status") != "done"]
        return incomplete

    @staticmethod
    def load(log_path: Path) -> Optional["TransactionLog"]:
        """
        Load existing transaction log from disk.

        Args:
            log_path: Path to transaction log file

        Returns:
            TransactionLog instance, or None if file doesn't exist/invalid
        """
        if not log_path.exists():
            return None

        try:
            with open(log_path, "r") as f:
                data = json.load(f)

            txn_log = TransactionLog(log_path)
            txn_log.entries = data.get("entries", [])
            return txn_log

        except Exception:
            return None

    def close(self) -> None:
        """Finalize transaction log (writes completed state to disk)."""
        self._write()
