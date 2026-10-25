"""Stand-ins for a cached analysis (embed.analyze()), with everything describe.py reads."""

import numpy as np

from synopsist import describe

INSTRUMENTS = ["piano", "drums", "synthesizer", "violin", "beat"]
MOODS = ["dream", "dark", "energetic", "advertising"]
GENRES = ["ambient", "electronic", "dance"]


def fake_analysis(duration=60.0, chords=("Am", "F"), sound=20.0, dynamics=4.0, instruments=("piano",),
                  mood="dream", genre="ambient", voice=0.1, danceable=0.9):
    frames = int(duration / describe.CHORD_HOP_S)
    patches = max(1, int(duration / describe.PATCH_HOP_S))

    def scores(labels, chosen, value):
        table = np.zeros((patches, len(labels)))
        for label in chosen:
            table[:, labels.index(label)] = value
        return table

    return {
        "duration_s": duration,
        "chords": np.array([chords[i * len(chords) // frames] for i in range(frames)]),
        "chord_strength": np.ones(frames),
        "spectral_complexity": np.full(frames, sound),
        "bands": np.ones((frames, 3)),
        "dynamic_complexity": dynamics,
        "notes": np.array([[i * 0.5, 0.4, 60 + (i % 5) * 2] for i in range(int(duration))]).reshape(-1, 3),
        "instruments": scores(INSTRUMENTS, instruments, 0.5), "instruments_labels": np.array(INSTRUMENTS),
        "moods": scores(MOODS, [mood], 0.3), "moods_labels": np.array(MOODS),
        "genres": scores(GENRES, [genre], 0.5), "genres_labels": np.array(GENRES),
        "voice": np.column_stack([np.full(patches, 1 - voice), np.full(patches, voice)]),
        "voice_labels": np.array(["instrumental", "voice"]),
        "danceability": np.column_stack([np.full(patches, danceable), np.full(patches, 1 - danceable)]),
        "danceability_labels": np.array(["danceable", "not_danceable"]),
    }
