"""Where a song's chorus is, from its cached analysis (embed.analyze()), for the song effects on the
website, which change when the chorus lands.

Most of these songs are instrumental, so the chorus is taken to be what it is in most electronic
music: the song's fullest parts, where everything plays at once, usually right after a build or a
break. Finding them takes three steps:

1. Cut the song into sections where its sound changes: peaks in a novelty curve (Foote's
   checkerboard kernel run down the self-similarity of the song's Discogs-EffNet embeddings and
   chroma, second by second), together with the places its intensity steps up or down.
2. Give every second an intensity: its loudness, bass, highs, and how dense the sound is (spectral
   complexity), each compared with the song's own loud parts on fixed scales, so a song that never
   changes level isn't stretched to look like one that does.
3. The chorus is the sections in the song's top tier of intensity: split the sections in two by
   intensity (Otsu's method, weighted by length), and split the upper group again while it still
   covers more than MAX_SHARE of the song. A song whose top tier isn't clearly above the rest has no
   chorus.

Each chorus then starts where it lands: the strongest rise in intensity near the start of its first
section, at a tenth of a second, moved onto the beat when one is that close.
"""

import numpy as np

STEP_S = 1.0  # the sections are cut on a grid of this many seconds
EFFNET_HOP_S = 62 * 256 / 16000  # embed.PATCH_HOP_S: one embedding every 0.992 s,
EFFNET_PATCH_S = 128 * 256 / 16000  # each describing 2.048 s (embed.PATCH_S)
FRAME_S = 4096 / 44100  # embed.CHROMA_FRAME / embed.SR: chroma, bands, and spectral complexity
LOUDNESS_HOP_S = 0.1  # embed.LOUDNESS_HOP_S: momentary loudness, 400 ms windows

# Intensity: each measure against its level in the song's loud parts (its LOUD_PARTS percentile),
# divided by a fixed unit (dB for the loudness and the bands; for the density, a factor of 2 ** 0.25,
# about 19% more spectral peaks), then weighted. Name -> (weight, unit).
INTENSITY = {"loudness": (0.35, 3.0), "bass": (0.2, 4.0), "density": (0.35, 0.25), "highs": (0.1, 4.0)}
LOUD_PARTS = 90
SIMILARITY_WEIGHTS = (0.6, 0.4)  # embeddings (the sound), chroma (the harmony)
KERNEL_S = 8  # the novelty kernel looks this far back and ahead
STEP_WINDOW_S = 6  # intensity steps: the average over this long after a moment minus before it
SHORTEST_SECTION_S = 8
BOUNDARY_PERCENTILE = 70  # a section boundary needs a novelty peak above this percentile of the curve
MAX_SHARE = 0.55  # at most this much of the song is chorus
SHORTEST_CHORUS_S = 12
MIN_CONTRAST = 0.5  # how much more intense than the rest of the song (intensity units) the chorus must be
SHORTEST_SONG_S = 30
# how far before and after a section boundary the landing is looked for: further after, because a
# chorus often follows a short break that the boundary comes before
LANDING_SEARCH_S = (2.0, 4.0)
LANDING_WINDOW_S = 0.6  # a landing is the largest rise from this long before a moment to this long after
BEAT_SNAP_S = 0.35  # a landing this close to a beat moves onto it


def _pool(times: np.ndarray, values, centers: np.ndarray, half: float) -> np.ndarray:
    """The mean of the rows of `values` whose times are within `half` of each center (the nearest
    row when none are)."""
    values = np.asarray(values, dtype=float)
    lo, hi = np.searchsorted(times, centers - half), np.searchsorted(times, centers + half)
    nearest = np.clip(np.searchsorted(times, centers), 0, len(values) - 1)
    return np.array([values[a:b].mean(axis=0) if b > a else values[n] for a, b, n in zip(lo, hi, nearest)])


def _smooth(x: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian smoothing (sigma in samples) that averages only the samples that exist near the ends."""
    radius = min(int(3 * sigma), (len(x) - 1) // 2)
    if radius < 1:
        return x
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    return np.convolve(x, kernel, mode="same") / np.convolve(np.ones(len(x)), kernel, mode="same")


def _intensity(loudness_db, bands_db, density) -> np.ndarray:
    """How full the sound is at each moment, from its loudness (dB), band levels (dB, columns bass,
    mids, highs), and spectral complexity, each against the song's own loud parts (0 there)."""
    density = np.log2(np.maximum(density, 1.0))
    parts = {"loudness": loudness_db, "bass": bands_db[:, 0], "density": density, "highs": bands_db[:, 2]}
    total = np.zeros(len(loudness_db))
    for name, (weight, unit) in INTENSITY.items():
        x = np.asarray(parts[name], dtype=float)
        total += weight * np.clip((x - np.percentile(x, LOUD_PARTS)) / unit, -4, 1.5)
    return total


def _measures(analysis, centers: np.ndarray, half: float):
    """Loudness (dB), band levels (dB), and spectral complexity, averaged around each center."""
    frames = np.arange(len(analysis["bands"])) * FRAME_S
    momentary = np.asarray(analysis["momentary_lufs"], dtype=float)
    loudness = _pool(np.arange(len(momentary)) * LOUDNESS_HOP_S + 0.2, 10 ** (momentary / 10), centers, half)
    bands = _pool(frames, analysis["bands"], centers, half)
    density = _pool(frames, analysis["spectral_complexity"], centers, half)
    return 10 * np.log10(loudness + 1e-12), 10 * np.log10(bands + 1e-12), density


def _unit_rows(x: np.ndarray) -> np.ndarray:
    x = x - x.mean(axis=0)
    return x / (np.linalg.norm(x, axis=1, keepdims=True) + 1e-9)


def _novelty(similarity: np.ndarray, half: int) -> np.ndarray:
    """Foote's novelty: a Gaussian-tapered checkerboard kernel run down the diagonal of the
    self-similarity matrix. High where the past and the future are each alike but unlike each other."""
    offsets = np.arange(-half, half) + 0.5
    taper = np.exp(-0.5 * (offsets / (half / 2)) ** 2)
    kernel = np.outer(taper, taper) * np.sign(np.outer(offsets, offsets))
    padded = np.pad(similarity, half, mode="edge")
    n = len(similarity)
    return np.maximum([(padded[i:i + 2 * half, i:i + 2 * half] * kernel).sum() for i in range(n)], 0)


def _peaks(score: np.ndarray, min_gap: int, threshold: float) -> list[int]:
    """The highest points of `score` above `threshold`, at least `min_gap` apart, in time order."""
    chosen = []
    for i in np.argsort(score)[::-1]:
        if score[i] < threshold:
            break
        if all(abs(i - j) >= min_gap for j in chosen):
            chosen.append(int(i))
    return sorted(chosen)


def _otsu(values: np.ndarray, weights: np.ndarray) -> float:
    """The threshold that best splits weighted values into a low and a high group."""
    order = np.argsort(values)
    v, w = values[order], weights[order]
    best, cut = -1.0, float(v[0])
    for i in range(1, len(v)):
        w0, w1 = w[:i].sum(), w[i:].sum()
        between = w0 * w1 * ((v[:i] * w[:i]).sum() / w0 - (v[i:] * w[i:]).sum() / w1) ** 2
        if between > best:
            best, cut = between, float((v[i - 1] + v[i]) / 2)
    return cut


def sections(analysis) -> tuple[np.ndarray, list[tuple[int, int]], np.ndarray]:
    """The song cut where its sound changes: the grid's centers (s), the sections as (first, end)
    indexes into the grid, and the intensity at each grid point."""
    duration = float(analysis["duration_s"])
    centers = np.arange(STEP_S / 2, duration, STEP_S)
    n = len(centers)
    embeddings = _pool(np.arange(len(analysis["embeddings"])) * EFFNET_HOP_S + EFFNET_PATCH_S / 2,
                       analysis["embeddings"], centers, max(STEP_S, EFFNET_HOP_S) / 2)
    chroma = _pool(np.arange(len(analysis["chroma"])) * FRAME_S, analysis["chroma"], centers, STEP_S / 2)
    intensity = _smooth(_intensity(*_measures(analysis, centers, STEP_S / 2)), 1.5)

    sound, harmony = (_unit_rows(x) for x in (embeddings, chroma))
    similarity = SIMILARITY_WEIGHTS[0] * sound @ sound.T + SIMILARITY_WEIGHTS[1] * harmony @ harmony.T
    novelty = _novelty(similarity, int(KERNEL_S / STEP_S))
    w = int(STEP_WINDOW_S / STEP_S)
    padded = np.pad(intensity, w, mode="edge")
    steps = np.abs([padded[i + w:i + 2 * w].mean() - padded[i:i + w].mean() for i in range(n)])
    score = 0.6 * novelty / (novelty.max() + 1e-9) + 0.4 * steps / (steps.max() + 1e-9)
    shortest = int(SHORTEST_SECTION_S / STEP_S)
    cuts = [b for b in _peaks(score, shortest, max(0.2, float(np.percentile(score, BOUNDARY_PERCENTILE))))
            if shortest // 2 <= b <= n - shortest // 2]
    edges = [0, *cuts, n]
    return centers, list(zip(edges[:-1], edges[1:])), intensity


def _landing(analysis, near_s: float, beats, rising: bool = True) -> float:
    """The moment near `near_s` (LANDING_SEARCH_S) where the intensity rises the most (or falls the
    most), moved onto the nearest beat if one is within BEAT_SNAP_S."""
    duration = float(analysis["duration_s"])
    hop = LOUDNESS_HOP_S
    w = int(LANDING_WINDOW_S / hop)
    before, after = LANDING_SEARCH_S if rising else LANDING_SEARCH_S[::-1]
    lo, hi = max(0.0, near_s - before - LANDING_WINDOW_S), min(duration, near_s + after + LANDING_WINDOW_S)
    times = np.arange(lo, hi, hop)
    if len(times) <= 2 * w:
        return near_s
    intensity = _smooth(_intensity(*_measures(analysis, times, hop)), 1.5)
    change = np.full(len(times), -np.inf)
    for i in range(w, len(times) - w):
        if -before <= times[i] - near_s <= after:
            change[i] = intensity[i:i + w].mean() - intensity[i - w:i].mean()
    if not rising:
        change[np.isfinite(change)] *= -1
    moment = float(times[int(np.argmax(change))])
    beats = np.asarray(beats, dtype=float)
    if len(beats):
        beat = float(beats[np.abs(beats - moment).argmin()])
        if abs(beat - moment) <= BEAT_SNAP_S:
            moment = beat
    return moment


def chorus(analysis) -> list[tuple[float, float]]:
    """The song's chorus: (start, end) in seconds for each time it plays, the start being the moment
    it lands. Empty when the song has no part clearly fuller than the rest."""
    duration = float(analysis["duration_s"])
    if duration < SHORTEST_SONG_S:
        return []
    # read once: a cached analysis opened with np.load reads its file again on every lookup
    analysis = {name: analysis[name] for name in
                ("duration_s", "embeddings", "chroma", "bands", "spectral_complexity", "momentary_lufs", "beats")}
    if len(analysis["embeddings"]) < 2:
        return []
    centers, cuts, intensity = sections(analysis)
    if len(cuts) < 2:
        return []
    level = np.array([intensity[a:b].mean() for a, b in cuts])
    length = np.array([b - a for a, b in cuts], dtype=float)

    top = np.ones(len(cuts), dtype=bool)  # the top tier, split off until it's small enough
    while top.sum() > 1:
        upper = top & (level > _otsu(level[top], length[top]))
        if not upper.any() or upper.all():
            break
        top = upper
        if length[top].sum() <= MAX_SHARE * length.sum():
            break
    if top.all():
        return []
    contrast = np.average(level[top], weights=length[top]) - np.average(level[~top], weights=length[~top])
    if contrast < MIN_CONTRAST:
        return []

    spans = []  # runs of neighboring top-tier sections
    for k in np.flatnonzero(top):
        a, b = cuts[k]
        if spans and spans[-1][1] == a:
            spans[-1][1] = b
        else:
            spans.append([a, b])
    found = []
    for a, b in spans:
        start = 0.0 if a == 0 else _landing(analysis, centers[a] - STEP_S / 2, analysis["beats"])
        end = duration if b == len(centers) else _landing(analysis, centers[b] - STEP_S / 2, analysis["beats"], rising=False)
        if end - start >= SHORTEST_CHORUS_S:
            found.append((round(start, 2), round(min(end, duration), 2)))
    return found
