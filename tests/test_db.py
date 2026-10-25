import sqlite3

import numpy as np
import pytest

from synopsist import db


@pytest.fixture
def conn(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    conn.execute("INSERT INTO tracks (track_id, title, album, file) VALUES ('a', 'A', 'X', 'X/A.mp3')")
    return conn


def features(embedding):
    return {"duration_s": 8.0, "bpm": 120.0, "bpm_confidence": 3.0, "key": "A", "scale": "major",
            "key_strength": 0.9, "loudness_lufs": -10.0, "peak_dbfs": -0.5, "onset_rate": 2.0, "embedding": embedding}


def segment(idx, embedding):
    return {"idx": idx, "start_s": 4.0 * idx, "end_s": 4.0 * idx + 4, "bpm": 120.0, "key": "A", "scale": "major",
            "key_strength": 0.9, "onset_rate": 2.0, "loudness_lufs": -10.0, "embedding": embedding}


def test_blob_roundtrip():
    vector = np.random.default_rng(0).normal(size=1280).astype(np.float32)
    assert np.array_equal(db.from_blob(db.to_blob(vector)), vector)


def test_save_analysis_replaces_segments(conn):
    e = np.ones(4, dtype=np.float32)
    db.save_analysis(conn, "a", features(e), [segment(0, e), segment(1, e), segment(2, e)],
                     file_sha1="abc", analysis_version=1, window_s=4.0)
    db.save_analysis(conn, "a", features(e), [segment(0, e), segment(1, e)],
                     file_sha1="abc", analysis_version=1, window_s=4.0)
    assert conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0] == 2
    track = conn.execute("SELECT * FROM tracks").fetchone()
    assert (track["file_sha1"], track["window_s"], track["bpm"]) == ("abc", 4.0, 120.0)
    assert np.array_equal(db.from_blob(track["embedding"]), e)


def test_removing_a_track_keeps_its_events(conn):
    e = np.ones(4, dtype=np.float32)
    db.save_analysis(conn, "a", features(e), [segment(0, e)], file_sha1="abc", analysis_version=1, window_s=4.0)
    conn.execute("""INSERT INTO events (user_id, track_id, event, from_s, to_s, client_ts)
                    VALUES ('anon_1', 'a', 'seek', 142.3, 118.0, '2026-10-05T21:14:03Z')""")
    conn.execute("DELETE FROM tracks WHERE track_id = 'a'")
    assert conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_unknown_event_type_is_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("""INSERT INTO events (user_id, track_id, event, position_s, client_ts)
                        VALUES ('anon_1', 'a', 'rewind', 10, '2026-10-05T21:14:03Z')""")


def test_old_database_gets_new_columns(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE tracks (track_id TEXT PRIMARY KEY, title TEXT NOT NULL, album TEXT NOT NULL, file TEXT NOT NULL)")
    old.execute("INSERT INTO tracks VALUES ('a', 'A', 'X', 'X/A.mp3')")
    old.commit()
    old.close()
    conn = db.connect(path)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tracks)")}
    assert set(db.ADDED_COLUMNS["tracks"]) <= columns
    assert tuple(conn.execute("SELECT track_id, title, track_no FROM tracks").fetchone()) == ("a", "A", None)
