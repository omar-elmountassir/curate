"""Progress tracking for long-running operations."""

import signal
import sys
from typing import Optional


class ProgressTracker:
    """
    Progress tracking with context manager and signal handling.

    Tracks progress of long-running operations and provides
    periodic reporting. Handles graceful shutdown on SIGINT/SIGTERM.
    """

    def __init__(
        self, total: Optional[int] = None, interval: int = 1000, desc: str = ""
    ) -> None:
        """
        Initialize progress tracker.

        Args:
            total: Total items to process (None for unknown)
            interval: Report progress every N items
            desc: Description prefix for progress messages
        """
        self.total = total
        self.interval = interval
        self.desc = desc
        self.count = 0
        self._shutdown_requested = False
        self._original_sigint = None
        self._original_sigterm = None

    def update(self, count: int = 1) -> None:
        """
        Increment progress counter.

        Args:
            count: Number of items to add (default: 1)
        """
        self.count += count
        self._maybe_report()

    def set_total(self, total: int) -> None:
        """
        Set total count for percentage calculation.

        Args:
            total: Total items to process
        """
        self.total = total
        self._maybe_report()

    def report(self) -> None:
        """Print current progress regardless of interval."""
        if self.total:
            pct = (self.count / self.total) * 100 if self.total > 0 else 0
            print(f"{self.desc}{self.count}/{self.total} ({pct:.1f}%)")
        else:
            print(f"{self.desc}{self.count} processed")

    def _maybe_report(self) -> None:
        """Report progress if interval reached."""
        if self.count % self.interval == 0:
            self.report()

    @property
    def shutdown_requested(self) -> bool:
        """Check if graceful shutdown was requested."""
        return self._shutdown_requested

    def _signal_handler(self, signum, frame) -> None:
        """Handle SIGINT/SIGTERM for graceful shutdown."""
        if not self._shutdown_requested:
            print("\nShutdown requested, finishing current operation...", file=sys.stderr)
            self._shutdown_requested = True
        else:
            # Force exit on second signal
            sys.exit(1)

    def __enter__(self) -> "ProgressTracker":
        """Enter context manager and register signal handlers."""
        self._original_sigint = signal.signal(signal.SIGINT, self._signal_handler)
        self._original_sigterm = signal.signal(signal.SIGTERM, self._signal_handler)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager and restore signal handlers."""
        if self._original_sigint:
            signal.signal(signal.SIGINT, self._original_sigint)
        if self._original_sigterm:
            signal.signal(signal.SIGTERM, self._original_sigterm)

        # Always report final count
        self.report()
        return False
