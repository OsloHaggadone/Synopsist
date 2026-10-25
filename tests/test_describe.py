import numpy as np
import pytest
from fakes import fake_analysis

from synopsist import describe
from synopsist.describe import (chord_measures, complexity, description, effective_count, instrument_measures,
                                melody_measures, tags)


def test_effective_count():
    assert effective_count([5, 5]) == pytest.approx(2.0)
    assert effective_count([1, 0, 0]) == pytest.approx(1.0)
    assert 1.3 < effective_count([9, 1]) < 1.5
    assert effective_count([]) == 0.0


def test_chord_measures_count_chords_and_changes():
    per = round(4 / describe.CHORD_HOP_S)  # 4 s of each chord
    chords = np.array(["Am"] * per + ["F"] * per + ["C"] * per + ["G"] * per)  # 16 s, 3 changes
    strength = np.ones(len(chords))
    variety, changes = chord_measures(chords, strength, duration_s=16.0)
    assert variety == pytest.approx(4.0, abs=0.05)
    assert changes == pytest.approx(3 / (16 / 60))
    flicker = chords.copy()
    flicker[per + 2] = "Dm"  # too short to hear as a change of chord
    assert chord_measures(flicker, strength, 16.0)[1] == pytest.approx(changes)
    assert chord_measures(chords, np.zeros(len(chords)), 16.0) == (0.0, 0.0)  # nothing clear enough to count


def test_melody_measures():
    pitches = [60, 62, 64, 65, 67, 69, 71, 72, 71, 69, 67, 65, 64, 62, 60]  # up a C major scale and back
    notes = np.array([[i * 0.5, 0.4, p] for i, p in enumerate(pitches)])  # start, length, MIDI pitch
    span, classes, steps = melody_measures(notes)
    assert span == pytest.approx(12, abs=1.5)
    assert 6 < classes <= 7  # its seven notes
    assert 1.5 < steps < 2.5  # in whole and half steps
    assert melody_measures(np.zeros((0, 3))) == (0.0, 0.0, 0.0)
    assert melody_measures(np.array([[i * 0.5, 0.4, 60] for i in range(20)])) == (0.0, 1.0, 1.0)  # one note


def test_instrument_measures():
    labels = np.array(["piano", "drums", "beat", "violin"])
    scores = np.zeros((60, 4))  # about a minute
    scores[:, 0] = 0.6  # piano all the way through
    scores[:, 2] = 0.9  # "beat" describes production, not an instrument
    scores[40:52, 3] = 0.5  # violin for 12 s
    scores[10, 1] = 0.9  # drums for a single moment: not enough to count
    assert instrument_measures(scores, labels) == (2, ["piano", "violin"])


def test_complexity_averages_its_five_parts():
    simple = complexity(fake_analysis(chords=("C",), sound=8, dynamics=1.5, instruments=("piano",)))
    busy = complexity(fake_analysis(chords=("Am", "F", "C", "G", "Dm", "Em", "E", "Bb"), sound=55, dynamics=9,
                                    instruments=("piano", "drums", "synthesizer", "violin")))
    for rating in (simple, busy):
        assert set(rating["parts"]) == set(describe.PARTS)
        assert all(0 <= value <= 100 for value in rating["parts"].values())
        assert rating["score"] == round(sum(rating["parts"].values()) / 5)
    assert simple["score"] < busy["score"]
    assert (simple["parts"]["sound"], busy["parts"]["sound"]) == (0, 100)
    assert (simple["chords_used"], busy["instruments"]) == (1.0, ["piano", "drums", "synthesizer", "violin"])


def test_tags():
    heard = tags(fake_analysis(mood="dark", genre="dance", instruments=("synthesizer",), voice=0.8, danceable=0.3))
    assert heard["moods"][0][0] == "dark" and heard["genres"][0][0] == "dance"
    assert heard["instruments"][0] == ("synthesizer", 0.5)
    assert all(name != "beat" for name, _ in heard["instruments"])
    assert (heard["voice"], heard["danceable"]) == (0.8, 0.3)


def test_description_says_what_the_song_is_and_how_it_moves():
    analysis = fake_analysis(mood="dream", genre="ambient", instruments=("piano", "synthesizer"))
    # 60 s: a quiet start, the bass from 0:12, a break from 0:24 to 0:36, the loudest moment at 0:36
    moments = [{"start": i * 4.0, "level": 20 if i < 2 else 70, "loudness": -12.0 if i < 2 else 2.0 if i == 9 else 0.0,
                "bass": 0 if i < 3 or 6 <= i < 9 else 80} for i in range(15)]
    text = description({"bpm": 70.0, "bpm_confidence": 3.0}, tags(analysis), complexity(analysis), moments)
    assert text.startswith("A dreamy ambient piece at a slow, unhurried pace, built from piano and synths. "
                           "It opens quietly, brings the bass in at 0:12, pulls it out for a break from 0:24 to 0:36, "
                           "and is at its fullest around 0:36.")
    calm_but_counted_double = description({"bpm": 160.0, "bpm_confidence": 3.0}, tags(analysis), complexity(analysis), [])
    assert "at an easy pace" in calm_but_counted_double and "vocals" not in calm_but_counted_double
