"""Cut songs into fixed windows. A segment is the unit that listening data (replays, skips) and
audio features are matched on; the same grid maps playback times to segments later."""

import numpy as np


def segment_bounds(duration_s: float, window_s: float) -> np.ndarray:
    """Contiguous [start, end) windows covering the whole song, shape (n, 2).

    A leftover shorter than half a window is merged into the last segment, so no segment is a
    tiny sliver; a longer leftover becomes a shorter final segment.
    """
    if duration_s <= 0 or window_s <= 0:
        raise ValueError("duration_s and window_s must be positive")
    n = int(duration_s // window_s)
    leftover = duration_s - n * window_s
    if n == 0 or leftover >= window_s / 2:
        n += 1
    starts = np.arange(n) * window_s
    ends = np.append(starts[1:], duration_s)
    return np.column_stack([starts, ends])


def locate(times, bounds: np.ndarray) -> np.ndarray:
    """Index of the segment each time (in seconds) falls in. Times outside the song are clamped
    to the first or last segment."""
    idx = np.searchsorted(bounds[:, 1], np.asarray(times, dtype=float), side="right")
    return np.clip(idx, 0, len(bounds) - 1)
