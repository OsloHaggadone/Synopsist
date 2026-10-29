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
    for site in ("https://oslohaggadone.com", "https://oslohaggadone.github.io"):  # the domain, and the old address
        allowed = client.options("/events", headers={"Origin": site, **asking})
        assert allowed.headers.get("access-control-allow-origin") == site
    other = client.options("/events", headers={"Origin": "https://example.com", **asking})
    assert "access-control-allow-origin" not in other.headers


# --- the same cases as the Worker (worker/), and what keeps spam out -----------------------------

import server  # noqa: E402

CASES = json.loads((Path(__file__).resolve().parents[1] / "worker" / "test" / "event-cases.json").read_text())


def when(value):
    """"now", "now-60d", "now+3d": a time relative to the test's (as worker/test/worker.test.js reads them)."""
    if not isinstance(value, str) or not value.startswith("now"):
        return value
    amount, unit = (int(value[3:-1]), value[-1]) if len(value) > 3 else (0, "s")
    unit = {"d": "days", "h": "hours", "m": "minutes", "s": "seconds"}[unit]
    return now(timedelta(**{unit: amount}))


def case_item(case):
    if "item" in case:
        return case["item"]
    item = CASES["base"] | case.get("change", {})
    for name in case.get("remove", []):
        item.pop(name)
    return item | {"timestamp": when(item["timestamp"])}


@pytest.mark.parametrize("case", CASES["cases"], ids=[case["name"] for case in CASES["cases"]])
def test_the_same_events_as_the_worker_are_stored_or_turned_away(tmp_path, case):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tracks": [{"id": id, "duration": length} for id, length in CASES["songs"].items()]}))
    database = tmp_path / "synopsist.db"
    client = TestClient(create_app(db_path=database, catalog=catalog))
    response = client.post("/events", content=json.dumps([case_item(case)]), headers={"Content-Type": "text/plain"})
    assert response.status_code == 200
    assert response.json()["stored"] == (1 if case["stored"] else 0)
    for name, value in case.get("expect", {}).items():
        assert stored(database)[-1][name] == value


def event(user=USER, track="song-a", **fields):
    return {"user_id": user, "track_id": track, "event": "play", "position_s": 1.0, "timestamp": now()} | fields


def test_other_websites_pages_cant_send(api):
    client, database = api
    assert client.post("/events", json=event(), headers={"Origin": "https://example.com"}).status_code == 403
    assert client.post("/events", json=event(), headers={"Origin": "https://oslohaggadone.com"}).json()["stored"] == 1
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
