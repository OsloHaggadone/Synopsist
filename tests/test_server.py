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


# --- what keeps spam out, the backups, and reading the data back -------------------------------

import sqlite3  # noqa: E402

import server  # noqa: E402


def event(user=USER, track="song-a", **fields):
    return {"user_id": user, "track_id": track, "event": "play", "position_s": 1.0, "timestamp": now()} | fields


def test_a_moment_past_the_end_of_the_song_is_turned_away(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tracks": [{"id": "song-a", "duration": 120.0}]}))
    client = TestClient(create_app(db_path=tmp_path / "s.db", catalog=catalog))
    batch = [event(position_s=121.5), event(position_s=130.0), event(event="seek", from_s=10.0, to_s=200.0)]
    assert client.post("/events", json=batch).json() == {"stored": 1, "rejected": 2}


def test_other_websites_pages_cant_send(api):
    client, database = api
    assert client.post("/events", json=event(), headers={"Origin": "https://example.com"}).status_code == 403
    assert client.post("/events", json=event(), headers={"Origin": "https://oslohaggadone.github.io"}).json()["stored"] == 1
    assert client.post("/events", json=event(), headers={"Origin": "http://testserver"}).json()["stored"] == 1  # its own page
    assert len(stored(database)) == 2


def test_a_listener_sending_more_than_anyone_listens_is_turned_away(api):
    client, database = api
    assert client.post("/events", json=[event()] * server.EVENTS_PER_MINUTE).json()["stored"] == server.EVENTS_PER_MINUTE
    assert client.post("/events", json=event()).status_code == 429
    other = "anon_" + "f" * 32  # someone else isn't held up
    assert client.post("/events", json=event(user=other)).json()["stored"] == 1


def test_one_connection_sending_too_many_requests_is_turned_away(api):
    client, _ = api
    users = ["anon_" + f"{n:032x}" for n in range(server.REQUESTS_PER_MINUTE + 1)]
    answers = [client.post("/events", json=event(user=user)).status_code for user in users]
    assert answers[:-1] == [200] * server.REQUESTS_PER_MINUTE and answers[-1] == 429


def test_a_days_worth_from_one_listener_is_all_it_takes(api):
    client, database = api
    conn = db.connect(database)
    db.save_events(conn, [{"user_id": USER, "track_id": "song-a", "event": "position", "position_s": 1.0,
                           "client_ts": now()}] * server.EVENTS_PER_DAY)
    conn.close()
    assert client.post("/events", json=event()).status_code == 429


def test_nothing_is_taken_once_the_disk_is_nearly_full(api, monkeypatch):
    client, database = api
    monkeypatch.setattr(server, "disk_used", lambda folder: 0.96)
    assert client.post("/events", json=event()).status_code == 507
    assert stored(database) == []


def test_the_database_is_backed_up_once_a_day(api):
    client, database = api
    client.post("/events", json=event())
    client.post("/events", json=event())
    copies = list((database.parent / "backups").glob("synopsist-*.db"))
    assert len(copies) == 1
    assert sqlite3.connect(copies[0]).execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_the_data_can_be_read_back_only_with_the_token(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tracks": [{"id": "song-a"}]}))
    client = TestClient(create_app(db_path=tmp_path / "s.db", catalog=catalog, admin_token="t0ken"))
    client.post("/events", json=event())
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "t0ken"}):
        assert client.get("/admin/status", headers=headers).status_code == 404
        assert client.get("/admin/backup", headers=headers).status_code == 404
    token = {"Authorization": "Bearer t0ken"}
    status = client.get("/admin/status", headers=token).json()
    assert status["events"] == 1 and status["listeners"] == 1 and 0 < status["disk_used_percent"] < 100
    copy = client.get("/admin/backup", headers=token)
    assert copy.content.startswith(b"SQLite format 3\x00")
    (tmp_path / "copy.db").write_bytes(copy.content)
    assert sqlite3.connect(tmp_path / "copy.db").execute("SELECT track_id FROM events").fetchall() == [("song-a",)]
    assert not list((tmp_path / "backups").glob("download-*"))  # the download's copy is gone again
    # without a token set, there's nothing there at all
    plain = TestClient(create_app(db_path=tmp_path / "s.db", catalog=catalog))
    assert plain.get("/admin/status", headers={"Authorization": "Bearer "}).status_code == 404


def test_the_api_alone(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tracks": [{"id": "song-a"}]}))
    client = TestClient(create_app(db_path=tmp_path / "s.db", catalog=catalog, website=False))
    assert client.get("/").json()["events"] == "POST /events"
    assert client.get("/js/app.js").status_code == 404
    assert client.post("/events", json=event()).json()["stored"] == 1


def test_the_songs_come_from_the_live_site_when_its_list_can_be_read(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tracks": [{"id": "song-a"}]}))

    class Answer:
        def __init__(self, text): self.text = text
        def read(self): return self.text.encode()
        def __enter__(self): return self
        def __exit__(self, *_): return False

    monkeypatch.setattr(server.urllib.request, "urlopen", lambda url, timeout: Answer(json.dumps({"tracks": [{"id": "new-song"}]})))
    client = TestClient(create_app(db_path=tmp_path / "s.db", catalog=catalog, catalog_url="https://example.com/catalog.json"))
    assert client.post("/events", json=[event(track="new-song"), event(track="song-a")]).json() == {"stored": 1, "rejected": 1}

    def unreachable(url, timeout):
        raise OSError("no connection")

    monkeypatch.setattr(server.urllib.request, "urlopen", unreachable)
    fallback = TestClient(create_app(db_path=tmp_path / "s2.db", catalog=catalog, catalog_url="https://example.com/catalog.json"))
    assert fallback.post("/events", json=event(track="song-a")).json()["stored"] == 1  # the file here, meanwhile
