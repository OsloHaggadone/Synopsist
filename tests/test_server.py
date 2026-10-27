import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from server import app  # noqa: E402

client = TestClient(app)


def test_serves_the_website():
    page = client.get("/")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert 'src="js/app.js"' in page.text
    assert client.get("/js/player.js").status_code == 200
    assert client.get("/no-such-file.mp3").status_code == 404


def test_byte_ranges_so_songs_can_be_seeked():
    full = client.get("/style.css")
    part = client.get("/style.css", headers={"Range": "bytes=10-29"})
    assert part.status_code == 206
    assert part.headers["content-range"] == f"bytes 10-29/{len(full.content)}"
    assert part.content == full.content[10:30]


# --- the listening-event API --------------------------------------------------------------------

import json  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402

from server import EVENTS_META, create_app  # noqa: E402
from synopsist import db  # noqa: E402

USER = "anon_" + "0123456789abcdef" * 2


def now(offset=timedelta(0)):
    return (datetime.now(timezone.utc) + offset).isoformat().replace("+00:00", "Z")


@pytest.fixture
def api(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tracks": [{"id": "song-a"}, {"id": "song-b"}]}))
    database = tmp_path / "synopsist.db"
    return TestClient(create_app(db_path=database, catalog=catalog)), database


def stored(database):
    conn = db.connect(database)
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM events ORDER BY event_id")]
    finally:
        conn.close()


def test_events_are_stored_as_sent(api):
    client, database = api
    batch = [
        {"user_id": USER, "track_id": "song-a", "event": "play", "position_s": 0, "timestamp": now()},
        {"user_id": USER, "track_id": "song-a", "event": "seek", "from_s": 142.3, "to_s": 118.0, "timestamp": now()},
        {"user_id": USER, "track_id": "song-a", "event": "ended", "position_s": 201.5, "timestamp": now()},
    ]
    # sent as text/plain, as the player does
    response = client.post("/events", content=json.dumps(batch), headers={"Content-Type": "text/plain"})
    assert response.json() == {"stored": 3, "rejected": 0}
    rows = stored(database)
    assert [row["event"] for row in rows] == ["play", "seek", "ended"]
    assert rows[1]["from_s"] == 142.3 and rows[1]["to_s"] == 118.0 and rows[1]["position_s"] is None
    assert rows[2]["position_s"] == 201.5 and rows[0]["client_ts"].endswith("Z")
    assert set(rows[0]) == {"event_id", "user_id", "track_id", "event", "position_s", "from_s", "to_s", "client_ts", "received_at"}


def test_one_event_on_its_own(api):
    client, database = api
    event = {"user_id": USER, "track_id": "song-b", "event": "pause", "position_s": 12.4, "timestamp": now()}
    assert client.post("/events", json=event).json() == {"stored": 1, "rejected": 0}
    assert stored(database)[0]["track_id"] == "song-b"


@pytest.mark.parametrize("change", [
    {"user_id": "anon_123"},  # not an ID the player makes
    {"user_id": "someone@example.com"},
    {"track_id": "not-a-song"},
    {"event": "like"},
    {"position_s": -1},
    {"position_s": True},
    {"position_s": "12"},
    {"position_s": None},
    {"timestamp": "2026-10-05T21:14:03"},  # no time zone
    {"timestamp": "yesterday"},
    {"timestamp": now(-timedelta(days=60))},
    {"timestamp": now(timedelta(days=3))},
])
def test_what_isnt_an_event_is_turned_away(api, change):
    client, database = api
    good = {"user_id": USER, "track_id": "song-a", "event": "play", "position_s": 3.0, "timestamp": now()}
    response = client.post("/events", json=[good, good | change])
    assert response.json() == {"stored": 1, "rejected": 1}
    assert len(stored(database)) == 1


def test_a_seek_needs_both_ends(api):
    client, _ = api
    seek = {"user_id": USER, "track_id": "song-a", "event": "seek", "from_s": 10, "timestamp": now()}
    assert client.post("/events", json=seek).json() == {"stored": 0, "rejected": 1}


def test_bad_requests(api):
    client, database = api
    assert client.post("/events", content="not json").status_code == 400
    assert client.post("/events", content="x" * 70_000).status_code == 413
    event = {"user_id": USER, "track_id": "song-a", "event": "play", "position_s": 0, "timestamp": now()}
    assert client.post("/events", json=[event] * 501).status_code == 413
    assert stored(database) == []


def test_the_page_says_where_the_api_is(api):
    client, _ = api
    assert EVENTS_META in client.get("/").text
    assert EVENTS_META in client.get("/index.html").text


def test_only_the_published_site_may_send_from_elsewhere(api):
    client, _ = api
    asking = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
    allowed = client.options("/events", headers={"Origin": "https://oslohaggadone.github.io", **asking})
    assert allowed.headers.get("access-control-allow-origin") == "https://oslohaggadone.github.io"
    other = client.options("/events", headers={"Origin": "https://example.com", **asking})
    assert "access-control-allow-origin" not in other.headers
