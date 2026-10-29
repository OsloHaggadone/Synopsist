"""SQLite storage: tracks, segments, and raw listening events."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from synopsist.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    track_id         TEXT PRIMARY KEY,   -- permanent id from data/catalog.csv
    title            TEXT NOT NULL,
    album            TEXT NOT NULL,
    release_date     TEXT,               -- YYYY-MM-DD, NULL until filled in
    file             TEXT NOT NULL,      -- path under data/stream/
    track_no         INTEGER,            -- position in its album: the song's row order in the catalog
    spotify_url      TEXT,
    apple_music_url  TEXT,
    amazon_music_url TEXT,
    duration_s       REAL,
    bpm              REAL,
    bpm_confidence   REAL,               -- 0 to 5.32; below ~1.5 the bpm is unreliable
    key              TEXT,
    scale            TEXT,               -- major or minor
    key_strength     REAL,
    loudness_lufs    REAL,               -- integrated loudness, for volume matching in the player
    peak_dbfs        REAL,               -- loudest sample, limits how far a quiet song can be raised
    onset_rate       REAL,               -- note/drum onsets per second
    embedding        BLOB,               -- whole-song Discogs-EffNet embedding, float32
    file_sha1        TEXT,               -- the audio the analysis below was computed from
    analysis_version INTEGER,
    window_s         REAL,               -- segment length the segments were cut with
    analyzed_at      TEXT
);

-- Segments are fixed windows of a song, rebuilt whenever its audio or the window length changes.
-- Refer to one by (track_id, idx).
CREATE TABLE IF NOT EXISTS segments (
    track_id      TEXT NOT NULL REFERENCES tracks (track_id) ON DELETE CASCADE,
    idx           INTEGER NOT NULL,      -- position in the song, from 0
    start_s       REAL NOT NULL,
    end_s         REAL NOT NULL,
    bpm           REAL,                  -- local tempo from the beats inside; NULL if under 3 beats
    key           TEXT,
    scale         TEXT,
    key_strength  REAL,
    onset_rate    REAL,
    loudness_lufs REAL,                  -- average momentary loudness
    embedding     BLOB NOT NULL,         -- mean Discogs-EffNet embedding, float32
    PRIMARY KEY (track_id, idx)
);

-- Raw events from the web player, never edited. No foreign key to tracks, so listening history
-- survives if a song is taken off the site.
CREATE TABLE IF NOT EXISTS events (
    event_id    INTEGER PRIMARY KEY,
    user_id     TEXT NOT NULL,           -- anonymous id stored in the listener's browser
    track_id    TEXT NOT NULL,
    event       TEXT NOT NULL CHECK (event IN ('play', 'pause', 'seek', 'skip', 'ended', 'position')),
    position_s  REAL,                    -- playhead, for every event except seek
    from_s      REAL,                    -- seek only
    to_s        REAL,                    -- seek only
    client_ts   TEXT NOT NULL,           -- "timestamp" sent by the player, ISO 8601 UTC
    received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS events_by_track ON events (track_id);
CREATE INDEX IF NOT EXISTS events_by_user ON events (user_id, track_id, client_ts);
"""

TRACK_FEATURES = ["duration_s", "bpm", "bpm_confidence", "key", "scale", "key_strength",
                  "loudness_lufs", "peak_dbfs", "onset_rate", "embedding"]

# Columns added after a table was first created. connect() adds any that an existing database is
# missing, so a schema change never means deleting the database (and its listening events).
ADDED_COLUMNS = {
    "tracks": {"track_no": "INTEGER", "spotify_url": "TEXT", "apple_music_url": "TEXT", "amazon_music_url": "TEXT",
               "peak_dbfs": "REAL", "artist": "TEXT"},
}
SEGMENT_COLUMNS = ["track_id", "idx", "start_s", "end_s", "bpm", "key", "scale", "key_strength",
                   "onset_rate", "loudness_lufs", "embedding"]
EVENT_COLUMNS = ["user_id", "track_id", "event", "position_s", "from_s", "to_s", "client_ts"]


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    """Open the database, creating it and its tables if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # lets the web server read while a write is going on
    conn.executescript(SCHEMA)
    for table, columns in ADDED_COLUMNS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, declaration in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
    return conn


def save_events(conn: sqlite3.Connection, events: list[dict]) -> None:
    """Store listening events as they came (app/server.py has checked them), all in one transaction."""
    with conn:
        conn.executemany(
            f"INSERT INTO events ({', '.join(EVENT_COLUMNS)}) VALUES ({', '.join(':' + c for c in EVENT_COLUMNS)})",
            [{column: event.get(column) for column in EVENT_COLUMNS} for event in events],
        )


def events_since(conn: sqlite3.Connection, user_id: str, since: str) -> int:
    """How many events a listener has sent since a time (ISO 8601 UTC, the way received_at is written)."""
    return conn.execute("SELECT COUNT(*) FROM events WHERE user_id = ? AND received_at >= ?", (user_id, since)).fetchone()[0]


def to_blob(vector) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def save_analysis(conn: sqlite3.Connection, track_id: str, track: dict, segments: list[dict], *,
                  file_sha1: str, analysis_version: int, window_s: float) -> None:
    """Store a song's features and replace its segments, all in one transaction."""
    values = {name: track[name] for name in TRACK_FEATURES}
    values["embedding"] = to_blob(values["embedding"])
    values |= {"track_id": track_id, "file_sha1": file_sha1, "analysis_version": analysis_version,
               "window_s": window_s, "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    assignments = ", ".join(f"{name} = :{name}" for name in values if name != "track_id")
    with conn:
        conn.execute(f"UPDATE tracks SET {assignments} WHERE track_id = :track_id", values)
        conn.execute("DELETE FROM segments WHERE track_id = ?", (track_id,))
        conn.executemany(
            f"INSERT INTO segments ({', '.join(SEGMENT_COLUMNS)}) "
            f"VALUES ({', '.join(':' + c for c in SEGMENT_COLUMNS)})",
            [seg | {"track_id": track_id, "embedding": to_blob(seg["embedding"])} for seg in segments],
        )
