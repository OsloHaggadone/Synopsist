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


def test_a_jump_back_counts_once_the_listener_stays(tmp_path):
    conn = db.connect(tmp_path / "synopsist.db")
    at = lambda s: f"2026-10-26T10:00:{s:06.3f}Z"
    db.save_events(conn, [
        # back to 0:29 and listening on: a replay, though the position update came a second later
        {"user_id": USER, "track_id": "song-a", "event": "seek", "from_s": 70.0, "to_s": 29.0, "client_ts": at(0)},
        {"user_id": USER, "track_id": "song-a", "event": "position", "position_s": 30.0, "client_ts": at(1)},
        # back, then away again a second later: not one
        {"user_id": USER, "track_id": "song-a", "event": "seek", "from_s": 45.0, "to_s": 20.0, "client_ts": at(10)},
        {"user_id": USER, "track_id": "song-a", "event": "seek", "from_s": 21.0, "to_s": 60.0, "client_ts": at(11)},
        # back, and paused before 3 seconds: not one either
        {"user_id": USER, "track_id": "song-a", "event": "seek", "from_s": 65.0, "to_s": 40.0, "client_ts": at(20)},
        {"user_id": USER, "track_id": "song-a", "event": "pause", "position_s": 41.0, "client_ts": at(21)},
        # the last thing the listener did: it counts
        {"user_id": USER, "track_id": "song-a", "event": "seek", "from_s": 50.0, "to_s": 10.0, "client_ts": at(30)},
    ])
    assert [e["to_s"] for e in events.jumps_back(conn)] == [29.0, 10.0]
