"""Reading the raw listening events (the events table, filled by app/server.py's POST /events).

For now this only looks at them: the latest ones, and every jump back within a song (a seek to an
earlier moment), which Phase 5 turns into replay scores per segment.
"""

import sqlite3

_FIELDS = """e.client_ts, e.user_id, e.track_id, COALESCE(t.title, e.track_id) AS title, e.event,
             e.position_s, e.from_s, e.to_s"""


def totals(conn: sqlite3.Connection) -> dict:
    """How many events there are, from how many listeners, about how many songs."""
    row = conn.execute("SELECT COUNT(*) AS events, COUNT(DISTINCT user_id) AS listeners, "
                       "COUNT(DISTINCT track_id) AS songs FROM events").fetchone()
    return dict(row)


def recent(conn: sqlite3.Connection, limit: int = 40) -> list[dict]:
    """The latest events, oldest first."""
    rows = conn.execute(f"SELECT {_FIELDS} FROM events e LEFT JOIN tracks t USING (track_id) "
                        "ORDER BY e.event_id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in reversed(rows)]


def jumps_back(conn: sqlite3.Connection, at_least_s: float = 1.0) -> list[dict]:
    """Every seek to an earlier moment of the same song, at least `at_least_s` back, oldest first."""
    rows = conn.execute(f"SELECT {_FIELDS} FROM events e LEFT JOIN tracks t USING (track_id) "
                        "WHERE e.event = 'seek' AND e.to_s < e.from_s - ? ORDER BY e.event_id",
                        (at_least_s,)).fetchall()
    return [dict(row) for row in rows]
