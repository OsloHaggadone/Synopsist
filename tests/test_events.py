from synopsist import db, events

USER = "anon_" + "ab" * 16


def test_recent_and_jumps_back(tmp_path):
    conn = db.connect(tmp_path / "synopsist.db")
    db.save_events(conn, [
        {"user_id": USER, "track_id": "song-a", "event": "play", "position_s": 0.0, "client_ts": "2026-10-26T10:00:00.000Z"},
        {"user_id": USER, "track_id": "song-a", "event": "seek", "from_s": 90.0, "to_s": 60.0, "client_ts": "2026-10-26T10:01:30.000Z"},
        {"user_id": USER, "track_id": "song-a", "event": "seek", "from_s": 70.0, "to_s": 120.0, "client_ts": "2026-10-26T10:02:00.000Z"},
        {"user_id": USER, "track_id": "song-a", "event": "seek", "from_s": 50.0, "to_s": 49.5, "client_ts": "2026-10-26T10:03:00.000Z"},
    ])
    assert events.totals(conn) == {"events": 4, "listeners": 1, "songs": 1}
    latest = events.recent(conn, limit=2)
    assert [e["client_ts"][14:16] for e in latest] == ["02", "03"]  # oldest first
    assert latest[0]["title"] == "song-a"  # no such song in the tracks table: its id instead
    back = events.jumps_back(conn)
    assert [(e["from_s"], e["to_s"]) for e in back] == [(90.0, 60.0)]  # forward, and a nudge, aren't replays
