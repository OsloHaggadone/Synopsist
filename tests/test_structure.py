import numpy as np
import pytest

from synopsist import structure

# A made-up song: (start, end, part), each part with its own sound, harmony, and level
INTRO, VERSE, CHORUS = 0, 1, 2
LAYOUT = [(0, 20, INTRO), (20, 50, VERSE), (50, 75, CHORUS), (75, 95, VERSE), (95, 120, CHORUS), (120, 130, INTRO)]
LEVELS = {  # momentary loudness (LUFS), power in the bass, mids, and highs, spectral complexity
    INTRO: (-30.0, (1e-4, 0.05, 0.01), 10.0),
    VERSE: (-16.0, (0.3, 0.3, 0.1), 20.0),
    CHORUS: (-10.0, (1.0, 0.6, 0.4), 35.0),
}


def song(layout=LAYOUT, levels=LEVELS, beat_offset=0.0, seed=0):
    """A cached analysis (embed.analyze()) with everything structure.py reads, at the real frame rates."""
    rng = np.random.default_rng(seed)
    duration = float(layout[-1][1])
    sound = rng.normal(size=(3, 16))  # one embedding direction per part
    harmony = rng.random((3, 12))

    def part(times):
        return np.array([next(p for start, end, p in layout if start <= t < end) if t < duration else layout[-1][2]
                         for t in times])

    patches = part(np.arange(int((duration - structure.EFFNET_PATCH_S) / structure.EFFNET_HOP_S) + 1)
                   * structure.EFFNET_HOP_S + structure.EFFNET_PATCH_S / 2)
    frames = part(np.arange(int(duration / structure.FRAME_S)) * structure.FRAME_S)
    loudness = part(np.arange(int(duration / structure.LOUDNESS_HOP_S)) * structure.LOUDNESS_HOP_S + 0.2)
    return {
        "duration_s": duration,
        "embeddings": sound[patches] + 0.3 * rng.normal(size=(len(patches), 16)),
        "chroma": harmony[frames] + 0.05 * rng.random((len(frames), 12)),
        "bands": np.array([levels[p][1] for p in frames]) * rng.uniform(0.8, 1.2, (len(frames), 3)),
        "spectral_complexity": np.array([levels[p][2] for p in frames]) + rng.normal(0, 1, len(frames)),
        "momentary_lufs": np.array([levels[p][0] for p in loudness]) + rng.normal(0, 0.3, len(loudness)),
        "beats": np.arange(beat_offset, duration, 0.5),  # 120 bpm
    }


def test_sections_are_cut_where_the_sound_changes():
    centers, cuts, intensity = structure.sections(song())
    starts = [centers[a] - structure.STEP_S / 2 for a, _ in cuts]
    assert starts[0] == 0
    for change in (20, 50, 75, 95, 120):
        assert min(abs(s - change) for s in starts) <= 1.5
    # the chorus is the most intense part, the intro the least
    assert intensity[60] > intensity[30] > intensity[10]


def test_chorus_is_the_fullest_part_each_time_it_plays():
    spans = structure.chorus(song())
    assert len(spans) == 2
    for (start, end), (expected_start, expected_end) in zip(spans, [(50, 75), (95, 120)]):
        assert start == pytest.approx(expected_start, abs=0.3)  # where it lands, on the beat
        assert end == pytest.approx(expected_end, abs=1.0)


def test_chorus_lands_on_the_beat():
    [(start, _), _] = structure.chorus(song(beat_offset=0.25))  # beats a quarter second off the change
    assert start == pytest.approx(50.25, abs=0.01)


def test_a_song_that_starts_with_its_chorus():
    layout = [(0, 30, CHORUS), (30, 60, VERSE), (60, 90, CHORUS), (90, 120, VERSE)]
    spans = structure.chorus(song(layout))
    assert [round(start) for start, _ in spans] == [0, 60]


def test_no_chorus_without_a_part_clearly_fuller_than_the_rest():
    flat = [(0, 40, VERSE), (40, 80, CHORUS), (80, 120, VERSE)]
    same = {VERSE: LEVELS[VERSE], CHORUS: LEVELS[VERSE]}  # different sound, same level
    assert structure.chorus(song(flat, same)) == []
    assert structure.chorus(song([(0, 20, VERSE), (20, 25, CHORUS)])) == []  # too short to tell
