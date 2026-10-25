import numpy as np
import pytest

from synopsist.segment import locate, segment_bounds


@pytest.mark.parametrize("duration, window, expected", [
    (8.0, 4.0, [(0, 4), (4, 8)]),  # exact fit
    (10.0, 4.0, [(0, 4), (4, 8), (8, 10)]),  # leftover of half a window or more: own segment
    (9.9, 4.0, [(0, 4), (4, 9.9)]),  # shorter leftover: merged into the last segment
    (3.0, 4.0, [(0, 3)]),  # song shorter than one window
])
def test_segment_bounds(duration, window, expected):
    assert np.allclose(segment_bounds(duration, window), expected)


@pytest.mark.parametrize("duration", [53.7, 99.03, 245.71, 455.26])
def test_segments_cover_the_song_without_gaps(duration):
    bounds = segment_bounds(duration, 4.0)
    assert bounds[0, 0] == 0 and bounds[-1, 1] == duration
    assert np.array_equal(bounds[1:, 0], bounds[:-1, 1])
    assert (bounds[:, 1] - bounds[:, 0] >= 2.0).all()


def test_locate():
    bounds = segment_bounds(10.0, 4.0)  # [0,4) [4,8) [8,10]
    assert list(locate([-1, 0, 3.99, 4.0, 7.5, 8.0, 10.0, 99], bounds)) == [0, 0, 0, 1, 1, 2, 2, 2]


def test_invalid_input():
    with pytest.raises(ValueError):
        segment_bounds(0, 4.0)
