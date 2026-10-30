import colorsys
import json
import shutil
import subprocess

import numpy as np
import pytest
from fakes import fake_analysis
from PIL import Image

from synopsist import db, mp3gain
from synopsist.publish import BAND_HOP_S, album_palette, band_curves, cover_colors, gain_steps, publish, wave_outline


def test_gain_steps():
    assert gain_steps(-14.0, -1.0) == 0
    assert gain_steps(-8.0, 1.0) == -4  # loud: turned down ~6 dB
    assert gain_steps(-24.0, -12.0) == 7  # quiet with headroom: raised ~10 dB, peak ends at -1.5 dBFS
    assert gain_steps(-24.0, -3.0) == 1  # quiet but with loud peaks: raised only as far as they allow
    assert gain_steps(-24.0, -1.2) == 0
    assert gain_steps(-8.0, 0.0, target_lufs=None) == 0


def test_band_curves_follow_the_bass_without_pulsing():
    t = np.arange(int(40 / BAND_HOP_S)) * BAND_HOP_S  # 40 s
    bass = np.where(t >= 20, 1.0, 1e-4) * (1 + 0.9 * np.sign(np.sin(2 * np.pi * 2 * t)))  # comes in at 20 s, hit twice a second
    mids = np.full(len(t), 0.3)
    highs = np.full(len(t), 1e-6)  # hardly any highs at all
    curves = band_curves(np.column_stack([bass, mids, highs]), duration_s=40.0)
    assert set(curves) == {"bass", "mids", "highs"} and len(curves["bass"]) == 160  # one value every 0.25 s
    b = np.array(curves["bass"])
    assert b[:60].max() < 10 and b[100:].min() > 70  # dark before the bass comes in, bright after
    assert np.ptp(b[100:-8]) <= 3  # and the drum hits don't make it pulse
    assert 60 < curves["mids"][40] < 100  # steady mids sit near their own loud level
    assert max(curves["highs"]) < 5  # a band far weaker than usual isn't turned up


def test_wave_outline():
    # 10 s: 5 s at 12 dB under the song's average loudness, then 5 s at its average (100 ms steps)
    wave = wave_outline(np.array([-26.0] * 50 + [-14.0] * 50), -14.0, duration_s=10.0)
    assert len(wave) == 160
    assert wave[10] < 30 and wave[150] > 70
    assert wave_outline(np.array([-70.0] * 30), -14.0, duration_s=3.0) == [0] * 160  # silence


def test_album_palette_gives_every_album_its_own_color():
    rng = np.random.default_rng(0)
    albums = {f"album-{n}": [{"embedding": db.to_blob(rng.normal(size=8))}] for n in range(5)}
    palette = album_palette(albums)
    assert set(palette) == set(albums)
    assert all(len(colors) == 4 for colors in palette.values())
    assert len({colors[0] for colors in palette.values()}) == 5
    assert album_palette({"solo": albums["album-0"]})["solo"][0].startswith("hsl(")


def test_cover_colors_come_from_the_artwork():
    image = Image.new("RGB", (100, 100), (20, 30, 120))
    image.paste((230, 90, 40), (0, 0, 100, 30))  # an orange band over 30% of a dark blue cover
    colors = cover_colors(image)
    assert len(colors) == 4
    hls = [colorsys.rgb_to_hls(*(int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))) for c in colors]
    assert abs(hls[0][0] - colorsys.rgb_to_hls(20 / 255, 30 / 255, 120 / 255)[0]) < 0.01  # blue first: most common
    assert hls[0][1] >= 0.57  # lifted so it shows up on a dark page
    assert abs(hls[1][0] - colorsys.rgb_to_hls(230 / 255, 90 / 255, 40 / 255)[0]) < 0.01  # then orange


def test_gray_artwork_gives_gray_colors():
    image = Image.new("RGB", (100, 100), (12, 12, 12))
    image.paste((70, 70, 70), (0, 0, 100, 30))  # a dark gray cover with a lighter band: no color at all
    colors = cover_colors(image)
    for color in colors:
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        assert r == g == b  # still gray (lifting its saturation turned gray into red)
    assert int(colors[0][1:3], 16) >= 0.57 * 255  # but lifted, so it shows up on a dark page


@pytest.fixture
def library(tmp_path):
    """Two albums of tiny real MP3s registered in a test database, one album with cover art."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("needs ffmpeg to make test MP3s")
    stream = tmp_path / "stream"
    conn = db.connect(tmp_path / "test.db")
    songs = [("loud", "A", "2024-05-01", -8.0, 1.0), ("quiet", "A", "2024-05-01", -24.0, -12.0),
             ("other", "B", None, -14.2, -2.0)]
    rng = np.random.default_rng(0)
    for n, (track_id, album, date, lufs, peak) in enumerate(songs):
        (stream / album).mkdir(parents=True, exist_ok=True)
        path = stream / album / f"{track_id}.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={300 + 100 * n}:duration=1",
                        "-c:a", "libmp3lame", "-b:a", "64k", str(path)], check=True)
        conn.execute(
            """INSERT INTO tracks (track_id, title, album, release_date, file, track_no, duration_s, loudness_lufs,
                                   peak_dbfs, file_sha1, embedding, analyzed_at)
               VALUES (?, ?, ?, ?, ?, ?, 1.0, ?, ?, ?, ?, 'now')""",
            (track_id, track_id.title(), album, date, f"{album}/{track_id}.mp3", n + 1, lufs, peak, f"sha{n}",
             db.to_blob(rng.normal(size=8))))
    conn.commit()
    Image.new("RGB", (1500, 1500), (120, 80, 200)).save(stream / "A" / "cover.png")
    analysis = tmp_path / "analysis"  # analyzed: loud and quiet, not other
    analysis.mkdir()
    for n in (0, 1):
        np.savez(analysis / f"sha{n}.npz", **fake_analysis(duration=1.0) | {
            "momentary_lufs": np.linspace(-30, -10, 10), "loudness_lufs": np.array(-14.0), "loudness_range": np.array(4.2),
            "bands": np.tile([4.0, 2.0, 1.0], (11, 1))})
    conn.execute("""INSERT INTO segments (track_id, idx, start_s, end_s, bpm, key, scale, key_strength, onset_rate,
                                          loudness_lufs, embedding)
                    VALUES ('loud', 0, 0.0, 1.0, 120.0, 'A', 'minor', 0.7, 3.0, -6.0, ?)""", (db.to_blob(np.zeros(8)),))
    conn.commit()
    return conn, stream, tmp_path / "library", analysis


def test_publish_writes_the_website_library(library):
    conn, stream, out, analysis = library
    summary = publish(conn, library=out, stream_dir=stream, audio_base_url="", target_lufs=-14.0, analysis_dir=analysis)
    assert (summary["songs"], summary["albums"], summary["new_files"]) == (3, 2, 3)
    assert (summary["lowered"], summary["raised"], summary["unchanged"]) == (1, 1, 1)

    catalog = json.loads((out / "catalog.json").read_text())
    a, b = catalog["albums"]
    assert (a["title"], a["year"], a["tracks"]) == ("A", 2024, ["loud", "quiet"])  # dated albums first
    assert (b["title"], b["year"], b["cover"], b["cover_large"]) == ("B", None, None, None)
    assert len(b["colors"]) == 4 and b["colors"][0].startswith("hsl(")  # chosen from its sound
    assert a["colors"][0] == "#815ccc"  # taken from its artwork (120, 80, 200), lifted
    for field, size in [("cover", 640), ("cover_large", 1400)]:
        with Image.open(out / a[field]) as cover:  # paths are relative to catalog.json
            assert cover.size == (size, size)

    tracks = {t["id"]: t for t in catalog["tracks"]}
    loud = tracks["loud"]
    assert loud["src"].startswith("audio/loud.") and loud["src"].endswith(".mp3")
    assert (loud["bpm"], loud["key"]) == (None, None)  # not analyzed in this test database
    assert (loud["release_date"], tracks["other"]["release_date"]) == ("2024-05-01", None)  # each song's own
    published = (out / loud["src"]).read_bytes()
    assert published == mp3gain.apply_gain((stream / "A" / "loud.mp3").read_bytes(), gain_steps(-8.0, 1.0))

    # the analyzed songs' analysis, for the backgrounds, the seek bar, and the details panel
    assert tracks["other"]["analysis"] is None
    details = json.loads((out / loud["analysis"]).read_text())
    assert details["hop"] == 0.25 and len(details["bass"]) == 4 and len(details["wave"]) == 160  # a 1 s song
    assert details["wave"] == sorted(details["wave"])  # the test song only gets louder
    assert details["chorus"] == []  # too short to have one (structure.py)
    song = details["song"]
    assert (song["loudness_lufs"], song["loudness_range"], song["stream_gain_db"]) == (-8.0, 4.2, -6.0)
    assert song["balance"] == {"bass": 57, "mids": 29, "highs": 14}  # power 4 : 2 : 1
    [moment] = details["moments"]
    assert (moment["start"], moment["end"], moment["key"], moment["loudness"]) == (0.0, 1.0, "A minor", 2.0)
    assert moment["level"] > 80 and moment["bass"] == moment["highs"] > 80  # every band at its own loud level
    assert json.loads((out / tracks["quiet"]["analysis"]).read_text())["moments"] == []
    # what the details panel says about it: complexity, what the classifiers hear, a description
    assert 0 <= song["complexity"]["score"] <= 100 and set(song["complexity"]["parts"]) == {
        "chords", "sound", "dynamics", "instruments", "melody"}
    assert details["tags"]["moods"][0] == ["dream", 0.3] and details["tags"]["instruments"][0] == ["piano", 0.5]
    assert details["description"].startswith("A dreamy ambient piece")


def test_publish_again_changes_nothing_and_cleans_up(library):
    conn, stream, out, analysis = library
    publish(conn, library=out, stream_dir=stream, audio_base_url="", target_lufs=-14.0, analysis_dir=analysis)
    catalog_time = (out / "catalog.json").stat().st_mtime_ns
    assert publish(conn, library=out, stream_dir=stream, audio_base_url="", target_lufs=-14.0, analysis_dir=analysis)["new_files"] == 0
    assert (out / "catalog.json").stat().st_mtime_ns == catalog_time

    # without volume matching the loud and quiet songs get new copies; the old ones are removed
    summary = publish(conn, library=out, stream_dir=stream, audio_base_url="https://cdn.example/", target_lufs=None,
                      analysis_dir=analysis)
    assert summary["new_files"] == 2
    assert len(list((out / "audio").iterdir())) == 3
    assert len(list((out / "analysis").iterdir())) == 2  # their analysis changed too (no volume change)
    catalog = json.loads((out / "catalog.json").read_text())
    assert all(t["src"].startswith("https://cdn.example/") for t in catalog["tracks"])


def test_the_songs_repository_keeps_its_own_files(library):
    conn, stream, out, analysis = library
    (out / "audio" / ".git").mkdir(parents=True)
    (out / "audio" / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (out / "audio" / "README.md").write_text("The website's songs\n")
    (out / "audio" / "gone.0123456789.mp3").write_bytes(b"a song taken off the site")
    publish(conn, library=out, stream_dir=stream, audio_base_url="", target_lufs=-14.0, analysis_dir=analysis)
    assert (out / "audio" / ".git" / "HEAD").exists() and (out / "audio" / "README.md").exists()
    assert not (out / "audio" / "gone.0123456789.mp3").exists()


def test_who_each_song_and_album_is_by(library):
    conn, stream, out, analysis = library
    conn.execute("UPDATE tracks SET artist = 'Someone Else' WHERE track_id = 'other'")
    conn.commit()
    publish(conn, library=out, stream_dir=stream, audio_base_url="", target_lufs=-14.0, analysis_dir=analysis)
    catalog = json.loads((out / "catalog.json").read_text())
    tracks = {t["id"]: t for t in catalog["tracks"]}
    assert tracks["loud"]["artist"] == "Oslo Haggadone"  # none in the catalog: config.ARTIST
    assert tracks["other"]["artist"] == "Someone Else"
    albums = {a["title"]: a for a in catalog["albums"]}
    assert (albums["A"]["artist"], albums["B"]["artist"]) == ("Oslo Haggadone", "Someone Else")
    conn.execute("UPDATE tracks SET artist = 'Someone Else' WHERE track_id = 'quiet'")  # album A: two artists now
    conn.commit()
    publish(conn, library=out, stream_dir=stream, audio_base_url="", target_lufs=-14.0, analysis_dir=analysis)
    albums = {a["title"]: a for a in json.loads((out / "catalog.json").read_text())["albums"]}
    assert albums["A"]["artist"] == "Various artists"
