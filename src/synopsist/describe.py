"""What the website says about a song beyond its measurements, from the cached analysis
(embed.analyze()): how complex it is and why, what Essentia's classifiers hear in it (moods, genres,
instruments, voice), and a short description for songs without a note in player/song-notes.md.

Complexity is the average of five parts, each 0 to 100:
- chords: how many different chords the song uses, and how often they change
- sound: how dense and layered the sound is (spectral complexity: the peaks in its spectrum)
- dynamics: how much the loudness moves (Essentia's dynamic complexity)
- instruments: how many different instruments the classifier hears over the whole song
- melody: how wide the main melody ranges, how many different notes it uses, and how varied its steps are
"""

import numpy as np

CHORD_HOP_S = 4096 / 44100  # embed.CHROMA_FRAME / embed.SR: one chord (and spectrum) per frame
PATCH_HOP_S = 62 * 256 / 16000  # embed.PATCH_HOP_S: one classifier row per embedding
CLEAR_CHORD = 0.5  # chord strength below this is too unclear to count (drums alone, noise)
SHORTEST_CHORD_S = 0.5  # shorter flickers between chords aren't counted as changes
INSTRUMENT_WINDOW_S = 8.0  # an instrument counts once its score, averaged over this long,
INSTRUMENT_PRESENT = 0.2  # reaches this somewhere in the song
# tags that describe production rather than an instrument you'd hear as its own part
NOT_INSTRUMENTS = {"beat", "computer", "sampler"}

# Each part's raw measure is mapped from its LOW (0) to its HIGH (100) and clamped. The ranges are
# fixed (set from the spread across the catalog, October 2026), so a song's rating doesn't change
# when other songs are added.
RANGES = {
    "chord_variety": (2.5, 7.5),  # effective number of chords
    "chord_changes": (8.0, 40.0),  # chord changes a minute
    "sound": (8.0, 55.0),  # median spectral complexity
    "dynamics": (1.5, 9.0),  # dynamic complexity, dB
    "instruments": (2.0, 9.0),  # instruments heard
    "melody_range": (10.0, 34.0),  # semitones
    "melody_notes": (3.5, 9.0),  # effective number of pitch classes
    "melody_steps": (5.0, 10.5),  # effective number of step sizes
}
PARTS = ("chords", "sound", "dynamics", "instruments", "melody")

# Classifier labels as words
NAMES = {
    "acousticbassguitar": "acoustic bass", "acousticguitar": "acoustic guitar", "classicalguitar": "classical guitar",
    "doublebass": "double bass", "drummachine": "drum machine", "electricguitar": "electric guitar",
    "electricpiano": "electric piano", "pipeorgan": "pipe organ", "easylistening": "easy listening",
    "darkambient": "dark ambient", "deephouse": "deep house", "drumnbass": "drum and bass",
    "instrumentalpop": "instrumental pop", "instrumentalrock": "instrumental rock", "newage": "new age",
    "alternativerock": "alternative rock", "classicrock": "classic rock", "acidjazz": "acid jazz",
    "jazzfusion": "jazz fusion", "electropop": "electropop", "poprock": "pop rock", "triphop": "trip hop",
    "worldfusion": "world fusion", "synthpop": "synthpop", "rnb": "R&B", "hiphop": "hip hop", "idm": "IDM",
    "edm": "EDM", "bossanova": "bossa nova", "dream": "dreamy",
}


def _name(label: str) -> str:
    return NAMES.get(label, label)


def _scale(value: float, measure: str) -> float:
    low, high = RANGES[measure]
    return float(np.clip((value - low) / (high - low), 0, 1) * 100)


def effective_count(weights) -> float:
    """How many things a distribution is spread over: 2 to the power of its entropy in bits. Two
    equally common chords count 2; one heard 90% of the time and another 10% count about 1.4."""
    p = np.asarray(weights, dtype=float)
    p = p[p > 0]
    if not len(p):
        return 0.0
    p = p / p.sum()
    return float(2 ** -(p * np.log2(p)).sum())


def chord_measures(chords, strength, duration_s: float) -> tuple[float, float]:
    """The effective number of chords the song uses, and how many times a minute the chord changes."""
    chords, strength = np.asarray(chords), np.asarray(strength)
    clear = chords[strength >= CLEAR_CHORD]
    if not len(clear):
        return 0.0, 0.0
    _, counts = np.unique(clear, return_counts=True)
    # runs of one chord, with flickers too short to hear as a change folded into the run before them
    runs = []
    for chord in clear:
        if runs and runs[-1][0] == chord:
            runs[-1][1] += 1
        else:
            runs.append([chord, 1])
    shortest = SHORTEST_CHORD_S / CHORD_HOP_S
    kept = []
    for chord, length in runs:
        if kept and (length < shortest or kept[-1][0] == chord):
            kept[-1][1] += length
        else:
            kept.append([chord, length])
    return effective_count(counts), (len(kept) - 1) / max(duration_s / 60, 1e-6)


def melody_measures(notes) -> tuple[float, float, float]:
    """The main melody's range in semitones (5th to 95th percentile of its notes), the effective
    number of different notes (pitch classes) it uses, and of different step sizes between notes."""
    notes = np.asarray(notes, dtype=float).reshape(-1, 3)
    if len(notes) < 8:
        return 0.0, 0.0, 0.0
    pitch = np.round(notes[:, 2]).astype(int)
    span = float(np.percentile(pitch, 95) - np.percentile(pitch, 5))
    classes = np.bincount(pitch % 12, weights=notes[:, 1], minlength=12)
    steps = np.minimum(np.abs(np.diff(pitch)), 12)
    return span, effective_count(classes), effective_count(np.bincount(steps, minlength=13))


def instrument_measures(activations, labels) -> tuple[int, list[str]]:
    """How many instruments the classifier clearly hears somewhere in the song, and which, most
    present first."""
    activations = np.asarray(activations, dtype=float).reshape(len(activations), -1)
    width = max(1, round(INSTRUMENT_WINDOW_S / PATCH_HOP_S))
    if len(activations) >= width:
        kernel = np.ones(width) / width
        smoothed = np.column_stack([np.convolve(column, kernel, mode="valid") for column in activations.T])
    else:
        smoothed = activations.mean(axis=0, keepdims=True)
    peak, mean = smoothed.max(axis=0), activations.mean(axis=0)
    heard = [i for i in np.argsort(-mean, kind="stable") if peak[i] >= INSTRUMENT_PRESENT and labels[i] not in NOT_INSTRUMENTS]
    return len(heard), [_name(str(labels[i])) for i in heard]


def complexity(analysis) -> dict:
    """The song's complexity, 0 to 100, its five parts, and what they're made of."""
    duration = float(analysis["duration_s"])
    variety, changes = chord_measures(analysis["chords"], analysis["chord_strength"], duration)
    sound = np.asarray(analysis["spectral_complexity"], dtype=float)
    loud = np.asarray(analysis["bands"], dtype=float).sum(axis=1)
    sound = sound[loud >= 1e-3 * np.median(loud)] if len(sound) == len(loud) and loud.any() else sound
    density = float(np.median(sound)) if len(sound) else 0.0
    count, instruments = instrument_measures(analysis["instruments"], analysis["instruments_labels"])
    span, notes, steps = melody_measures(analysis["notes"])
    parts = {
        "chords": (_scale(variety, "chord_variety") + _scale(changes, "chord_changes")) / 2,
        "sound": _scale(density, "sound"),
        "dynamics": _scale(float(analysis["dynamic_complexity"]), "dynamics"),
        "instruments": _scale(count, "instruments"),
        "melody": (_scale(span, "melody_range") + _scale(notes, "melody_notes") + _scale(steps, "melody_steps")) / 3,
    }
    return {
        "score": round(sum(parts.values()) / len(parts)),
        "parts": {name: round(value) for name, value in parts.items()},
        "chords_used": round(variety, 1),
        "chord_changes": round(changes, 1),  # a minute
        "instruments": instruments,
        "melody_range": round(span),  # semitones
    }


def _top(activations, labels, n: int, skip=()) -> list[tuple[str, float]]:
    mean = np.asarray(activations, dtype=float).mean(axis=0)
    order = [i for i in np.argsort(-mean, kind="stable") if str(labels[i]) not in skip]
    return [(str(labels[i]), round(float(mean[i]), 3)) for i in order[:n]]


def tags(analysis) -> dict:
    """What the classifiers hear in the song as a whole: its strongest moods and themes, genres,
    and instruments (each with its average score, 0 to 1), how likely it has a voice, and how
    danceable it is."""
    voice = list(analysis["voice_labels"]).index("voice")
    danceable = list(analysis["danceability_labels"]).index("danceable")
    return {
        "moods": _top(analysis["moods"], analysis["moods_labels"], 5),
        "genres": _top(analysis["genres"], analysis["genres_labels"], 3),
        "instruments": [(_name(label), score) for label, score in
                        _top(analysis["instruments"], analysis["instruments_labels"], 4, skip=NOT_INSTRUMENTS)],
        "voice": round(float(np.mean(np.asarray(analysis["voice"])[:, voice])), 2),
        "danceable": round(float(np.mean(np.asarray(analysis["danceability"])[:, danceable])), 2),
    }


# --- a description in words, for songs without a note --------------------------------------------

# Moods and themes as words. The classifier's other tags (advertising, corporate, background, and
# so on) say where music tends to be used rather than how it feels, so they're left out.
MOODS = {
    "dream": "dreamy", "space": "spacey", "relaxing": "relaxed", "calm": "calm", "meditative": "meditative",
    "dark": "dark", "deep": "deep", "energetic": "energetic", "happy": "bright", "positive": "bright",
    "epic": "epic", "film": "cinematic", "movie": "cinematic", "trailer": "cinematic", "drama": "dramatic",
    "dramatic": "dramatic", "emotional": "emotional", "melodic": "melodic", "inspiring": "uplifting",
    "uplifting": "uplifting", "motivational": "uplifting", "hopeful": "hopeful", "soft": "soft", "sad": "sad",
    "melancholic": "melancholic", "romantic": "romantic", "love": "tender", "summer": "sunny", "fun": "playful",
    "funny": "playful", "party": "party-ready", "groovy": "groovy", "upbeat": "upbeat", "powerful": "powerful",
    "heavy": "heavy", "action": "driving", "adventure": "adventurous", "soundscape": "atmospheric",
    "retro": "retro", "cool": "cool", "game": "game-like", "slow": "laid-back", "fast": "fast",
}
CALM = {"relaxing", "meditative", "calm", "slow", "dream", "soft"}  # a fast tempo with these is likely counted double
NOTICEABLE = 0.04  # a mood or instrument scoring less than this on average isn't worth naming
STYLES = {"easylistening": "easy-listening", "chillout": "chill-out", "darkambient": "dark ambient",
          "drumnbass": "drum and bass", "newage": "new age", "hiphop": "hip hop"}
PIECES = {"ambient", "soundtrack", "classical", "orchestral", "newage", "darkambient"}  # "a piece", not "a track"
SOUNDS = {"synthesizer": "synths", "keyboard": "keys", "drum machine": "a drum machine", "electric piano": "electric piano"}
STANDS_OUT = {
    "chords": ("the harmony keeps moving through many chords", "the harmony stays with a few chords"),
    "sound": ("the sound is dense and layered", "the sound stays sparse and open"),
    "dynamics": ("it swings between quiet and loud", "the loudness stays even"),
    "instruments": ("plenty of instruments come and go", "a small set of sounds carries it"),
    "melody": ("the melody ranges widely", "the melody keeps to a narrow range"),
}


def _clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def _join(words: list[str]) -> str:
    if len(words) < 3:
        return " and ".join(words)
    return f"{', '.join(words[:-1])}, and {words[-1]}"


def _what_it_is(track: dict, heard: dict) -> str:
    moods = list(dict.fromkeys(MOODS[label] for label, score in heard["moods"] if label in MOODS and score >= NOTICEABLE))[:2]
    genre = heard["genres"][0][0] if heard["genres"] else "electronic"
    kind = "piece" if genre in PIECES or heard["danceable"] < 0.5 else "track"
    bpm, steady = track.get("bpm"), (track.get("bpm_confidence") or 0) >= 1.5
    if bpm and bpm >= 130 and (heard["danceable"] < 0.6 or any(label in CALM for label, _ in heard["moods"][:3])):
        bpm /= 2  # a calm song "at 160 BPM" is felt at 80
    pace = ("with a loose, flowing pulse" if not bpm or not steady else
            "at a slow, unhurried pace" if bpm < 75 else "at an easy pace" if bpm < 95 else
            "at an unhurried mid-tempo" if bpm < 115 else "at a brisk pace" if bpm < 135 else "at a fast pace")
    words = ", ".join(moods + [STYLES.get(genre, genre)]).replace(f", {STYLES.get(genre, genre)}", f" {STYLES.get(genre, genre)}")
    article = "An" if words[0].lower() in "aeiou" else "A"
    sounds = [SOUNDS.get(name, name) for name, score in heard["instruments"][:3] if score >= NOTICEABLE]
    built = f", built from {_join(sounds)}" if sounds else ""
    voice = ", with vocals" if heard["voice"] >= 0.75 else ""
    return f"{article} {words} {kind} {pace}{built}{voice}."


def _how_it_moves(moments: list[dict], parts: dict) -> str:
    if len(moments) < 4:
        return ""
    levels = np.array([m["level"] for m in moments], dtype=float)
    typical = float(np.median(levels))
    said = []
    if levels[:2].mean() < typical - 25:
        said.append("opens quietly")
    bass_in = next((i for i, m in enumerate(moments) if m["bass"] >= 50), None)
    if bass_in is not None and bass_in >= 2:
        said.append(f"brings the bass in at {_clock(moments[bass_in]['start'])}")
    gap = range(0)
    if bass_in is not None:  # a break: the bass gone for 12 s or more, then back before the end
        start = None
        for i in range(bass_in + 1, len(moments) - 2):
            if moments[i]["bass"] < 25:
                start = i if start is None else start
            elif start is not None:
                if i - start >= 3:
                    gap = range(start, i)
                    it = "it" if said and said[-1].startswith("brings the bass") else "the bass"
                    said.append(f"pulls {it} out for a break from {_clock(moments[start]['start'])} to {_clock(moments[i]['start'])}")
                    break
                start = None
    loudness = [m["loudness"] if m["loudness"] is not None and i not in gap else -99 for i, m in enumerate(moments)]
    peak = int(np.argmax(loudness))
    if peak >= 2:
        said.append(f"is at its fullest around {_clock(moments[peak]['start'])}")
    if len(levels) >= 12 and levels[-4:].mean() < typical - 25:  # a long fade, 16 s or more
        said.append("fades out slowly at the end")
    if not said:
        return "It holds one steady level from start to finish." if parts["dynamics"] < 25 else ""
    return f"It {_join(said)}."


def _what_stands_out(parts: dict) -> str:
    high, low = max(parts, key=parts.get), min(parts, key=parts.get)
    said = []
    if parts[high] >= 70:
        said.append(STANDS_OUT[high][0])
    if parts[low] <= 25:
        said.append(STANDS_OUT[low][1])
    if not said:
        return ""
    text = f"{said[0]}, while {said[1]}" if len(said) == 2 else said[0]
    return text[0].upper() + text[1:] + "."


def description(track: dict, heard: dict, rating: dict, moments: list[dict]) -> str:
    """A few plain sentences about a song, for its details panel when it has no note of its own:
    what it is (mood, style, pace, main sounds), how it moves (quiet starts, where the bass comes in
    or takes a break, its fullest moment, a fade), and what stands out in its complexity. `track` is
    its row in the tracks table, `heard` its tags(), `rating` its complexity(), `moments` the
    segments as published (with level, loudness, and bass)."""
    sentences = [_what_it_is(track, heard), _how_it_moves(moments, rating["parts"]), _what_stands_out(rating["parts"])]
    return " ".join(s for s in sentences if s)
