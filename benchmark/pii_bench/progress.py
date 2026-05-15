"""Tiny dependency-free progress reporter. One line, overwritten with ``\\r``,
ETA computed from elapsed wall-clock and completed fraction.
"""

from __future__ import annotations

import sys
import time


def _fmt_eta(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:  # NaN
        return "?"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


class Progress:
    """Single-line progress display.

    Usage::

        pr = Progress("paired", total=220)
        for i in range(220):
            ...
            pr.tick()
        pr.done()
    """

    def __init__(self, label: str, total: int, *, stream=None, enabled: bool = True):
        self.label = label
        self.total = max(int(total), 1)
        self.current = 0
        self.start = time.perf_counter()
        self.stream = stream or sys.stderr
        self.enabled = enabled and self.stream.isatty()
        # Throttle so we don't spam the terminal in tight loops.
        self._last_render = 0.0

    def tick(self, n: int = 1, suffix: str = "") -> None:
        self.current += n
        now = time.perf_counter()
        if not self.enabled:
            return
        # Render at most ~10 fps, but always render the final tick.
        if (now - self._last_render) < 0.1 and self.current < self.total:
            return
        self._last_render = now
        elapsed = now - self.start
        frac = self.current / self.total
        eta = (elapsed / frac - elapsed) if frac > 0 else float("nan")
        bar_w = 24
        filled = int(bar_w * frac)
        bar = "█" * filled + "·" * (bar_w - filled)
        msg = (f"\r  {self.label} [{bar}] "
               f"{self.current}/{self.total}  "
               f"elapsed {_fmt_eta(elapsed)}  ETA {_fmt_eta(eta)}")
        if suffix:
            msg += f"  {suffix}"
        # Pad to clear any leftover characters from prior longer line.
        self.stream.write(msg + " " * 4)
        self.stream.flush()

    def done(self, note: str = "") -> None:
        if self.enabled:
            elapsed = time.perf_counter() - self.start
            self.stream.write(
                f"\r  {self.label}: {self.current}/{self.total} done in "
                f"{_fmt_eta(elapsed)}{('  — ' + note) if note else ''}"
                + " " * 20 + "\n"
            )
            self.stream.flush()
        else:
            elapsed = time.perf_counter() - self.start
            print(f"  {self.label}: {self.current}/{self.total} done in "
                  f"{_fmt_eta(elapsed)}{('  — ' + note) if note else ''}",
                  file=self.stream)
