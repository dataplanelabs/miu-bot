"""Stream buffer for accumulating and debouncing LLM output."""

from __future__ import annotations

import time


class StreamBuffer:
    """Accumulates streamed tokens and provides debounced snapshots."""

    def __init__(self, debounce_interval: float = 1.5, min_chars: int = 30):
        self._buffer = ""
        self._debounce = debounce_interval
        self._min_chars = min_chars
        self._last_flush_time = 0.0
        self._last_flushed_len = 0
        self._done = False

    def append(self, text: str) -> None:
        self._buffer += text

    def should_flush(self) -> bool:
        """Check if enough time and content for a flush."""
        if self._done:
            return True
        now = time.monotonic()
        new_chars = len(self._buffer) - self._last_flushed_len
        time_ok = (now - self._last_flush_time) >= self._debounce
        chars_ok = new_chars >= self._min_chars
        return time_ok and chars_ok

    def flush(self) -> str:
        """Return current accumulated content and mark as flushed."""
        self._last_flush_time = time.monotonic()
        self._last_flushed_len = len(self._buffer)
        return self._buffer

    def finish(self) -> str:
        """Mark stream as done and return final content."""
        self._done = True
        return self._buffer

    @property
    def content(self) -> str:
        return self._buffer

    @property
    def is_done(self) -> bool:
        return self._done
