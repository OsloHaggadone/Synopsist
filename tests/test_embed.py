import wave

import numpy as np
import pytest

from synopsist import embed
from synopsist.segment import segment_bounds

SR = 44100


def test_segment_features_math():
    n_patches = 11
    analysis = {
        "duration_s": 12.0,
        "embeddings": np.repeat(np.arange(n_patches, dtype=np.float32)[:, None], 1280, axis=1),
        "beats": np.arange(0, 12, 0.5, dtype=np.float32),  # 120 BPM
        "onsets": np.arange(0, 12, 0.25, dtype=np.float32),  # 4 per second
        "chroma": np.zeros((int(12 * SR / embed.CHROMA_FRAME), 12), dtype=np.float32),  # silence
        "momentary_lufs": np.full(120, -20.0, dtype=np.float32),
    }
    segments = embed.segment_features(analysis, segment_bounds(12.0, 4.0))
    assert [s["idx"] for s in segments] == [0, 1, 2]
    for s in segments:
        assert s["bpm"] == pytest.approx(120)
        assert s["onset_rate"] == pytest.approx(4.0)
        assert s["loudness_lufs"] == pytest.approx(-20.0)
        assert s["key"] is None and s["key_strength"] == 0.0
        assert s["embedding"].shape == (1280,)
    means = [s["embedding"][0] for s in segments]
    assert means == sorted(means) and means[0] < 3 < means[-1]  # each segment averages its own patches


def synthetic_song(path, seconds=30, bpm=120):
    """A sustained A major chord with a kick drum on every beat."""
    t = np.arange(int(seconds * SR)) / SR
    chord = sum(np.sin(2 * np.pi * f * h * t) / h for f in (220.0, 277.18, 329.63) for h in (1, 2, 3))
    kick = np.zeros_like(t)
    beat_len = int(0.12 * SR)
    envelope = np.exp(-np.arange(beat_len) / (0.03 * SR))
    for start in (np.arange(0, seconds, 60 / bpm) * SR).astype(int):
        end = min(start + beat_len, len(t))
        kick[start:end] += envelope[:end - start] * np.sin(2 * np.pi * 60 * np.arange(end - start) / SR)
    audio = 0.1 * chord / 3 + 0.6 * kick
    samples = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(samples.tobytes())
    return samples


@pytest.mark.skipif(not embed.models_ready(), reason="run scripts/build_catalog.py once to download the models")
def test_analyze_synthetic_song(tmp_path):
    path = tmp_path / "song.wav"
    samples = synthetic_song(path)
    analysis = embed.analyze(path)

    assert analysis["duration_s"] == pytest.approx(30, abs=0.01)
    assert analysis["bpm"] == pytest.approx(120, abs=1.5)
    assert len(analysis["onsets"]) / 30 == pytest.approx(2, abs=0.5)
    assert analysis["embeddings"].shape == (29, 1280)
    assert analysis["peak_dbfs"] == pytest.approx(20 * np.log10(np.abs(samples).max() / 32768), abs=0.1)
    bass, mids, highs = analysis["bands"].mean(axis=0)
    assert analysis["bands"].shape == (len(analysis["chroma"]), 3)
    assert bass > highs  # the test song's 60 Hz kick sits in the bass band
    assert 0 <= analysis["loudness_range"] < 3  # the same chord and kick throughout
    assert analysis["dynamic_complexity"] < 3
    chords, counts = np.unique(analysis["chords"], return_counts=True)
    assert chords[counts.argmax()] == "A"  # the A major chord, all the way through
    assert analysis["spectral_complexity"].shape == (len(analysis["chroma"]),) and analysis["spectral_complexity"].mean() > 1
    assert analysis["melody_hz"].max() > 0 and analysis["notes"].shape[1] == 3
    assert analysis["instruments"].shape == (29, len(analysis["instruments_labels"])) == (29, 40)
    assert set(analysis["voice_labels"]) == {"instrumental", "voice"}

    track = embed.track_features(analysis)
    assert (track["key"], track["scale"]) == ("A", "major")
    segments = embed.segment_features(analysis, segment_bounds(analysis["duration_s"], 4.0))
    assert len(segments) == 8 and segments[-1]["end_s"] == analysis["duration_s"]
    assert all(s["bpm"] == pytest.approx(120, abs=1.5) for s in segments)
