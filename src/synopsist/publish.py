"""Publish the music library the website plays from: player/library/ (generated; don't edit).

- audio/<track_id>.<version>.mp3: every song, volume-matched to config.STREAM_LUFS without
  re-encoding (see mp3gain.py). The version in the name changes whenever the audio does, so
  browsers and caches never play an outdated copy.
- covers/<album>-<size>.<version>.jpg: album art from data/stream/<album>/cover.jpg, resized for
  the album list (640 px) and the full-screen view (1400 px).
- analysis/<track_id>.<version>.json: what the website does with each song's analysis: the bass,
  mids, and highs curves its backgrounds follow while the song plays, when its chorus plays (for the
  song effects, structure.py), the outline drawn along the seek bar, and what the song's details
  panel shows: a description in words (for songs without a note in player/song-notes.md), the
  measurements with the complexity rating (describe.py), and each of its moments (segments). The
  version is a hash of the content.
- catalog.json: the albums and songs, in the order the website shows them, with each album's colors
  (from its artwork, or chosen from its sound when it has none). Paths in it are relative to it.
"""

import colorsys
import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
from PIL import Image

from synopsist import describe, mp3gain, structure
from synopsist.config import ANALYSIS_DIR, ARTIST, AUDIO_BASE_URL, LIBRARY_DIR, STREAM_DIR, STREAM_LUFS
from synopsist.db import from_blob
from synopsist.ingest import cover_image, slugify
from synopsist.segment import locate

PEAK_CEILING_DBFS = -1.0  # a quiet song is raised at most until its loudest sample reaches this
COVER_SIZES = {"cover": 640, "cover_large": 1400}  # pixels: album list and lock screen; full screen
COVER_HUES = (175, 335)  # teal through violet to pink: the site's own color range

# Each song's analysis for the website (song_analysis()), from the analysis cache. The frame steps
# are embed.py's: band power every 4096 samples at 44.1 kHz, momentary loudness every 100 ms.
BAND_HOP_S = 4096 / 44100
MOMENTARY_HOP_S = 0.1
BANDS = ("bass", "mids", "highs")  # embed.BANDS_HZ
# Band curves for the backgrounds: each band's power is averaged over a few seconds (a Gaussian with
# this standard deviation), so a bassline coming in brightens the backgrounds but drum hits don't
# make them pulse, then compared with the band's loud parts in the same song (its 95th percentile)
# through an S-curve centered BAND_CENTER_DB below them. A band far weaker than usual (a song with
# hardly any bass, say) is compared with BAND_FLOOR_DB below the loud parts of the whole sound
# instead, so it stays low rather than being turned up to the level of a song full of bass.
CURVE_HOP_S = 0.25
BAND_SMOOTH_S = 1.0
BAND_CENTER_DB = -5.0
BAND_WIDTH_DB = 3.5
BAND_FLOOR_DB = (-4.0, -6.0, -14.0)
# The seek bar's outline: the song's loudness in WAVE_POINTS equal slices, from WAVE_FLOOR_DB below
# the song's average loudness (empty) to WAVE_TOP_DB above it (full height), on a curve that spreads
# out the loud end, where mastered songs spend most of their time.
WAVE_POINTS = 160
WAVE_FLOOR_DB = -20.0
WAVE_TOP_DB = 4.0
WAVE_CURVE = 1.6


def gain_steps(loudness_lufs: float | None, peak_dbfs: float | None, target_lufs: float | None = STREAM_LUFS) -> int:
    """Global-gain steps that bring a song closest to the target loudness without raising its
    loudest sample above PEAK_CEILING_DBFS."""
    if target_lufs is None or loudness_lufs is None:
        return 0
    steps = round((target_lufs - loudness_lufs) / mp3gain.STEP_DB)
    while steps > 0 and (peak_dbfs or 0.0) + steps * mp3gain.STEP_DB > PEAK_CEILING_DBFS:
        steps -= 1
    return steps


def album_palette(albums: dict[str, list[dict]]) -> dict[str, list[str]]:
    """Four colors per album for albums without artwork: the first two paint the cover drawn in its
    place, all four the full-screen backdrop. Albums are lined up by how they sound (along the main
    direction in which their average embeddings differ) and spread evenly over COVER_HUES, so every
    album gets its own color and similar-sounding albums get neighboring ones."""
    ids = list(albums)
    if len(ids) > 1:
        vectors = np.array([np.mean([from_blob(t["embedding"]) for t in albums[i]], axis=0) for i in ids])
        centered = vectors - vectors.mean(axis=0)
        direction = np.linalg.svd(centered, full_matrices=False)[2][0]
        order = np.argsort(centered @ (direction if direction.sum() >= 0 else -direction))
    else:
        order = [0]
    low, high = COVER_HUES
    palette = {}
    for rank, i in enumerate(order):
        hue = low + (high - low) * (rank / (len(ids) - 1) if len(ids) > 1 else 0.5)
        palette[ids[i]] = [f"hsl({hue:.0f} 70% 55%)", f"hsl({(hue + 35) % 360:.0f} 70% 15%)",
                           f"hsl({(hue - 40) % 360:.0f} 75% 45%)", f"hsl({(hue + 80) % 360:.0f} 65% 40%)"]
    return palette


# The lightest and least saturated a color taken from artwork may be: hue stays the artwork's, but
# moody, dark covers still give the site an album stripe you can see and a full-screen backdrop
# that glows. The first color is the album's accent; the second stays deep.
COLOR_FLOORS = [(0.58, 0.42), (0.16, 0.3), (0.46, 0.38), (0.36, 0.36)]  # (lightness, saturation)
# Artwork with hardly any color (under GRAY_SHARE of its pixels with channels GRAY_CHROMA or more
# apart, out of 255) gives grays, only lightened: a gray has no hue, and saturating one paints it
# red, colorsys's hue for gray. (The least colorful official cover, Hollow Journey's, has 19%.)
GRAY_CHROMA, GRAY_SHARE = 12, 0.02


def _lift(rgb: tuple[int, int, int], lightness: float, saturation: float) -> str:
    hue, light, sat = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    r, g, b = colorsys.hls_to_rgb(hue, max(light, lightness), max(sat, saturation))
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def cover_colors(image: Image.Image) -> list[str]:
    """Four colors from the artwork: its most common colors, skipping near-duplicates, most common
    first, lifted to COLOR_FLOORS (gray artwork's only in lightness)."""
    small = image.convert("RGB").resize((64, 64))
    quantized = small.quantize(colors=12, method=Image.Quantize.MEDIANCUT)
    flat = quantized.getpalette()
    picked = []
    for _, index in sorted(quantized.getcolors(), reverse=True):
        rgb = tuple(flat[index * 3:index * 3 + 3])
        if all(sum((a - b) ** 2 for a, b in zip(rgb, other)) > 48 ** 2 for other in picked):
            picked.append(rgb)
        if len(picked) == 4:
            break
    picked += [picked[n % len(picked)] for n in range(4 - len(picked))]  # artwork with few colors
    pixels = np.asarray(small, dtype=int)
    gray = ((pixels.max(axis=2) - pixels.min(axis=2)) >= GRAY_CHROMA).mean() < GRAY_SHARE
    return [_lift(rgb, lightness, 0 if gray else saturation) for rgb, (lightness, saturation) in zip(picked, COLOR_FLOORS)]


def _percent(values) -> list[int]:
    return [int(v) for v in np.round(np.clip(values, 0, 1) * 100)]


def _round(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def _smooth(values: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian smoothing down the first axis (sigma in rows). Near the ends it averages only the
    rows that exist, so a song doesn't fade in or out."""
    radius = min(int(3 * sigma), (len(values) - 1) // 2)
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    weight = np.convolve(np.ones(len(values)), kernel, mode="same")
    return np.column_stack([np.convolve(column, kernel, mode="same") / weight for column in values.T])


def band_curves(bands: np.ndarray, duration_s: float) -> dict[str, list[int]]:
    """How strong the bass, mids, and highs are at each moment of a song, 0 to 100, one value every
    CURVE_HOP_S seconds (value i is centered on (i + 0.5) * CURVE_HOP_S)."""
    power = _smooth(np.asarray(bands, dtype=float), BAND_SMOOTH_S / BAND_HOP_S)
    level = 10 * np.log10(power + 1e-12)
    whole = np.percentile(10 * np.log10(power.sum(axis=1) + 1e-12), 95)
    relative = level - np.maximum(np.percentile(level, 95, axis=0), whole + np.array(BAND_FLOOR_DB))
    frames = np.arange(len(level)) * BAND_HOP_S  # frame centers
    centers = (np.arange(max(1, int(np.ceil(duration_s / CURVE_HOP_S)))) + 0.5) * CURVE_HOP_S
    return {name: _percent(1 / (1 + np.exp(-(np.interp(centers, frames, relative[:, n]) - BAND_CENTER_DB) / BAND_WIDTH_DB)))
            for n, name in enumerate(BANDS)}


def _wave_height(relative_db) -> np.ndarray:
    """0 to 1 for a loudness compared with the song's average (dB)."""
    return np.clip((np.asarray(relative_db, dtype=float) - WAVE_FLOOR_DB) / (WAVE_TOP_DB - WAVE_FLOOR_DB), 0, 1) ** WAVE_CURVE


def wave_outline(momentary_lufs: np.ndarray, integrated_lufs: float, duration_s: float) -> list[int]:
    """The song's shape for the seek bar: its loudness in WAVE_POINTS equal slices, 0 to 100."""
    centers = np.arange(len(momentary_lufs)) * MOMENTARY_HOP_S + 0.2  # 400 ms windows
    which = np.minimum((centers / duration_s * WAVE_POINTS).astype(int), WAVE_POINTS - 1)
    power = np.bincount(which, 10 ** (np.asarray(momentary_lufs, dtype=float) / 10), WAVE_POINTS)
    count = np.bincount(which, minlength=WAVE_POINTS)
    have = count > 0  # a very short song has slices no window is centered in: they take their neighbors'
    slices = np.arange(WAVE_POINTS)
    loudness = np.interp(slices, slices[have], 10 * np.log10(power[have] / count[have]))
    return _percent(_wave_height(loudness - integrated_lufs))


def song_analysis(track: dict, analysis, segments: list[dict], gain_db: float) -> dict:
    """What the website shows of one song's analysis. `track` is its row in the tracks table,
    `analysis` its cached analysis (embed.analyze()), `segments` its rows in the segments table, and
    `gain_db` how much louder (or quieter) the website's copy of it is."""
    duration, integrated = track["duration_s"], track["loudness_lufs"]
    curves = band_curves(analysis["bands"], duration)
    power = np.asarray(analysis["bands"], dtype=float).sum(axis=0)
    centers = (np.arange(len(curves["bass"])) + 0.5) * CURVE_HOP_S
    bounds = np.array([[s["start_s"], s["end_s"]] for s in segments]).reshape(-1, 2)
    where = locate(centers, bounds) if len(bounds) else np.zeros(0, dtype=int)
    moments = []
    for idx, s in enumerate(segments):
        inside = where == idx
        if not inside.any():  # a moment shorter than a curve step: use the nearest value
            inside = np.abs(centers - (s["start_s"] + s["end_s"]) / 2) == np.abs(centers - (s["start_s"] + s["end_s"]) / 2).min()
        relative = None if s["loudness_lufs"] is None else s["loudness_lufs"] - integrated
        moments.append({
            "start": round(s["start_s"], 2),
            "end": round(s["end_s"], 2),
            "loudness": _round(relative),  # dB, compared with the whole song
            "level": 0 if relative is None else _percent([_wave_height(relative)])[0],  # as drawn in the seek bar
            "bpm": _round(s["bpm"]),
            "key": f"{s['key']} {s['scale']}" if s["key"] else None,
            "key_strength": _round(s["key_strength"], 2),
            "onset_rate": _round(s["onset_rate"], 2),
            **{name: round(float(np.mean(np.asarray(curves[name])[inside]))) for name in BANDS},
        })
    rating, heard = describe.complexity(analysis), describe.tags(analysis)
    return {
        "song": {
            "duration": round(duration, 2),
            "bpm": _round(track["bpm"]),
            "bpm_confidence": _round(track["bpm_confidence"], 2),  # 0 to 5.32; under ~1.5 the tempo is a guess
            "key": f"{track['key']} {track['scale']}" if track["key"] else None,
            "key_strength": _round(track["key_strength"], 2),
            "loudness_lufs": round(integrated, 1),
            "loudness_range": round(float(analysis["loudness_range"]), 1),  # LU (EBU R128 loudness range)
            "peak_dbfs": _round(track["peak_dbfs"]),
            "onset_rate": _round(track["onset_rate"], 2),  # notes and hits per second
            "stream_gain_db": round(gain_db, 1),  # the website's copy is this much louder (or quieter)
            "balance": dict(zip(BANDS, _percent(power / power.sum()) if power.sum() > 0 else [0, 0, 0])),  # % of power
            "complexity": rating,
        },
        "tags": heard,
        "description": describe.description(track, heard, rating, moments),
        "hop": CURVE_HOP_S,
        **curves,
        "chorus": [list(span) for span in structure.chorus(analysis)],  # [start, end] in seconds, each time it plays
        "wave": wave_outline(analysis["momentary_lufs"], integrated, duration),
        "moments": moments,
    }


def _publish_analysis(details: dict, track_id: str, analysis_dir: Path) -> str:
    """Write a song's analysis for the website unless the same file exists already."""
    text = json.dumps(details, ensure_ascii=False, separators=(",", ":")) + "\n"
    name = f"{track_id}.{hashlib.sha1(text.encode()).hexdigest()[:10]}.json"
    if not (analysis_dir / name).exists():
        (analysis_dir / name).write_text(text, encoding="utf-8")
    return name


def _publish_audio(src: Path, audio_dir: Path, track_id: str, file_sha1: str, steps: int) -> tuple[str, bool, bool]:
    """Write the streaming copy unless it exists already. Returns its file name, whether it was
    written now, and whether the volume could be changed (False only for files that aren't MP3s)."""
    name = f"{track_id}.{hashlib.sha1(f'{file_sha1}:{steps}'.encode()).hexdigest()[:10]}.mp3"
    if (audio_dir / name).exists():
        return name, False, True
    tmp = audio_dir / f"{name}.tmp"
    adjusted = mp3gain.copy_with_gain(src, tmp, steps)
    tmp.replace(audio_dir / name)
    return name, True, adjusted


def _publish_cover(src: Path, covers_dir: Path, album_id: str) -> tuple[dict[str, str], list[str]]:
    """Write the resized copies of the album art that don't exist yet. Returns their file names by
    catalog field, and the artwork's colors."""
    data = src.read_bytes()
    names = {}
    with Image.open(src) as image:
        image = image.convert("RGB")
        for field, size in COVER_SIZES.items():
            name = f"{album_id}-{size}.{hashlib.sha1(data + str(size).encode()).hexdigest()[:10]}.jpg"
            names[field] = name
            if not (covers_dir / name).exists():
                copy = image.copy()
                copy.thumbnail((size, size), Image.Resampling.LANCZOS)
                copy.save(covers_dir / name, "JPEG", quality=85, optimize=True, progressive=True)
        colors = cover_colors(image)
    return names, colors


def publish(conn: sqlite3.Connection, library: Path = LIBRARY_DIR, stream_dir: Path = STREAM_DIR,
            audio_base_url: str = AUDIO_BASE_URL, target_lufs: float | None = STREAM_LUFS,
            analysis_dir: Path = ANALYSIS_DIR) -> dict:
    """Write player/library/ for every analyzed song and return a summary of what was done."""
    rows = [dict(r) for r in conn.execute(
        """SELECT track_id, title, artist, album, release_date, file, track_no, spotify_url, apple_music_url,
                  amazon_music_url, duration_s, bpm, bpm_confidence, key, scale, key_strength, loudness_lufs,
                  peak_dbfs, onset_rate, file_sha1, embedding
           FROM tracks WHERE analyzed_at IS NOT NULL ORDER BY album, track_no""")]
    audio_dir, covers_dir, details_dir = library / "audio", library / "covers", library / "analysis"
    for folder in (audio_dir, covers_dir, details_dir):
        folder.mkdir(parents=True, exist_ok=True)
    summary = {"songs": len(rows), "albums": 0, "new_files": 0, "raised": 0, "lowered": 0, "unchanged": 0,
               "limited_by_peak": 0, "not_adjustable": []}
    keep, tracks, by_album = set(), [], {}

    for row in rows:
        steps = gain_steps(row["loudness_lufs"], row["peak_dbfs"], target_lufs)
        wanted = gain_steps(row["loudness_lufs"], -99.0, target_lufs)  # with unlimited headroom
        summary["raised" if steps > 0 else "lowered" if steps < 0 else "unchanged"] += 1
        summary["limited_by_peak"] += steps < wanted
        name, written, adjusted = _publish_audio(stream_dir / row["file"], audio_dir, row["track_id"],
                                                 row["file_sha1"], steps)
        summary["new_files"] += written
        if not adjusted:
            summary["not_adjustable"].append(row["track_id"])
        keep.add(name)
        details = None
        cached = analysis_dir / f"{row['file_sha1']}.npz"  # embed.cache_path()
        if cached.exists():
            segments = [dict(s) for s in conn.execute(
                "SELECT * FROM segments WHERE track_id = ? ORDER BY idx", (row["track_id"],))]
            with np.load(cached) as analysis:
                details = _publish_analysis(song_analysis(row, analysis, segments, steps * mp3gain.STEP_DB),
                                            row["track_id"], details_dir)
            keep.add(details)
        album_id = slugify(row["album"]) or "album"
        by_album.setdefault(album_id, []).append(row)
        tracks.append({
            "id": row["track_id"],
            "title": row["title"],
            "artist": row["artist"] or ARTIST,
            "album": album_id,
            "track_no": row["track_no"],
            "release_date": row["release_date"] or None,
            "duration": round(row["duration_s"], 2),
            "bpm": round(row["bpm"]) if row["bpm"] else None,
            "key": f"{row['key']} {row['scale']}" if row["key"] else None,
            "src": audio_base_url + name if audio_base_url else f"audio/{name}",
            "spotify": row["spotify_url"],
            "apple_music": row["apple_music_url"],
            "amazon_music": row["amazon_music_url"],
            "analysis": f"analysis/{details}" if details else None,
        })

    albums = []
    palette = album_palette(by_album)
    for album_id, album_rows in by_album.items():
        date = max((r["release_date"] for r in album_rows if r["release_date"]), default=None)
        cover = cover_image((stream_dir / album_rows[0]["file"]).parent)
        names, colors = _publish_cover(cover, covers_dir, album_id) if cover else ({}, palette[album_id])
        keep.update(names.values())
        # the album's artist: its songs' one artist, or "Various artists" when they differ
        artists = {r["artist"] or ARTIST for r in album_rows}
        albums.append({
            "id": album_id,
            "title": album_rows[0]["album"],
            "artist": artists.pop() if len(artists) == 1 else "Various artists",
            "release_date": date,
            "year": int(date[:4]) if date else None,
            **{field: f"covers/{names[field]}" if names else None for field in COVER_SIZES},
            "colors": colors,
            "tracks": [r["track_id"] for r in album_rows],
        })
    # newest release first; albums without a release date after them, alphabetically
    albums.sort(key=lambda a: a["title"].lower())
    albums.sort(key=lambda a: a["release_date"] or "", reverse=True)
    summary["albums"] = len(albums)

    for folder in (audio_dir, covers_dir, details_dir):
        for path in folder.iterdir():
            if path.name not in keep:
                path.unlink()

    text = json.dumps({"albums": albums, "tracks": tracks}, ensure_ascii=False, indent=1) + "\n"
    catalog = library / "catalog.json"
    if not catalog.exists() or catalog.read_text(encoding="utf-8") != text:
        catalog.write_text(text, encoding="utf-8")
    return summary
