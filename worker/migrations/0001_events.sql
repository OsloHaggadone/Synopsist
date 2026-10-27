-- The live site's listening events: the events table app/server.py fills on this computer
-- (src/synopsist/db.py), without its indexes. On D1's free plan each index costs one more row written
-- per event, and the data is looked at in a copy (data/live.db, from scripts/pull_events.py) that
-- gets them.
CREATE TABLE IF NOT EXISTS events (
    event_id    INTEGER PRIMARY KEY,
    user_id     TEXT NOT NULL,
    track_id    TEXT NOT NULL,
    event       TEXT NOT NULL CHECK (event IN ('play', 'pause', 'seek', 'skip', 'ended', 'position')),
    position_s  REAL,
    from_s      REAL,
    to_s        REAL,
    client_ts   TEXT NOT NULL,
    received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
