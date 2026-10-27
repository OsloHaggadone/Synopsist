"""Synopsist web server on this computer: the website and its music from player/, and the
listening-event API, writing to data/synopsist.db. Online, the same API runs on Cloudflare
(worker/: the live site's), and checks events the same way: the same cases
(worker/test/event-cases.json) are run against both, by tests/test_server.py and by worker/'s tests.

POST /events takes the player's raw listening events (CLAUDE.md, "Event format"): one event, or a
list of them, as JSON. It's read whatever the content type says, since the player sends it as
text/plain (a page may send that to another site without asking first, and navigator.sendBeacon
carries it). Each event is checked against what the player sends and stored as it came, in the
events table; the backend works out what counts as a replay later (Phase 5). Nothing about the
request is kept: no IP address, no headers, and no access log, since the privacy note promises that
listening data is linked only to the random ID made in the listener's browser.

What it turns away, so spam isn't stored (with js/listening.js's settling, all of the self-check so
far: ROADMAP, Phase 4):
- events that aren't ones the player sends: a song not on the website, a moment past the song's
  end, an ID the player wouldn't make, a time that isn't believable;
- requests from other websites' pages (only the published site's, and the page's own server's);
- more than a listener sends: EVENTS_PER_MINUTE or EVENTS_PER_DAY (a UTC day) from one ID, and from
  one connection REQUESTS_PER_MINUTE or CONNECTION_EVENTS_PER_MINUTE. A connection's address is only
  held in memory for that minute, to count with, and never written down.

Serving the website too, it tells the page where the API is (a meta tag in index.html, read by
player/js/listening.js); the published site sends to SITE.eventsUrl (site.js), the Worker.

Run:  python app/server.py      then open http://localhost:8000
"""

import argparse
import json
import math
import os
import re
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synopsist import db
from synopsist.config import DB_PATH, LIBRARY_DIR, PLAYER_DIR

EVENTS = {"play", "pause", "seek", "skip", "ended", "position"}
USER_ID = re.compile(r"anon_[0-9a-f]{32}")  # js/listening.js: "anon_" and 16 random bytes
MAX_BODY_BYTES = 64 * 1024
MAX_BATCH = 500  # events in one request
MAX_SECONDS = 6 * 60 * 60  # a playhead past this isn't in any song
PAST_THE_END_S = 2.0  # nor one this far past the song's length (the player rounds; a little slack)
TOO_OLD = timedelta(days=30)  # events the player held on to longer than this aren't taken
TOO_NEW = timedelta(days=1)  # nor any from a clock this far ahead
# How much one listener sends: about 5 events a minute (the position every 15 s, and what they press)
EVENTS_PER_MINUTE = 120
EVENTS_PER_DAY = 6000  # in a UTC day (listening around the clock is 5,760 position events)
# One connection, which a household or a dorm may share: a page sends a request every 30 s or so
REQUESTS_PER_MINUTE = 60
CONNECTION_EVENTS_PER_MINUTE = 300
ORIGINS = [origin for origin in os.environ.get("SYNOPSIST_ORIGINS", "https://oslohaggadone.github.io").split(",") if origin]
EVENTS_META = '<meta name="synopsist-events" content="events">'


class KnownTracks:
    """The songs on the website and their lengths (track id -> seconds), from library/catalog.json,
    read again whenever it's rebuilt."""

    def __init__(self, catalog: Path):
        self.catalog = catalog
        self.stamp = None
        self.songs: dict[str, float | None] = {}

    def get(self) -> dict:
        try:
            stamp = self.catalog.stat().st_mtime_ns
        except OSError:
            return self.songs
        if stamp != self.stamp:
            tracks = json.loads(self.catalog.read_text(encoding="utf-8"))["tracks"]
            self.songs = {track["id"]: track.get("duration") for track in tracks}
            self.stamp = stamp
        return self.songs


class Limiter:
    """How much each key (a listener's ID, or a connection's address) sent in the last minute. In
    memory only: an address is never written down, and is forgotten once its minute is over."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.sent: dict[str, deque] = {}

    def allow(self, key: str, amount: int = 1) -> bool:
        now = time.monotonic()
        if len(self.sent) > 10_000:  # the keys that have gone quiet go
            self.sent = {k: window for k, window in self.sent.items() if window and window[-1][0] > now - 60}
        window = self.sent.setdefault(key, deque())
        while window and window[0][0] <= now - 60:
            window.popleft()
        if sum(n for _, n in window) + amount > self.per_minute:
            return False
        window.append((now, amount))
        return True


def seconds(value) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and 0 <= value <= MAX_SECONDS
    except OverflowError:  # a whole number too big to be a float
        return False


def client_time(value) -> str | None:
    """The player's timestamp, in UTC, if it's an ISO 8601 time with a time zone and a believable one."""
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    now = datetime.now(timezone.utc)
    if not now - TOO_OLD <= moment <= now + TOO_NEW:
        return None
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def clean(item, songs: dict) -> dict | None:
    """An event as it's stored, or None if it isn't one the player sends."""
    if not isinstance(item, dict):
        return None
    user, track, kind = item.get("user_id"), item.get("track_id"), item.get("event")
    if not (isinstance(user, str) and USER_ID.fullmatch(user)) or not isinstance(track, str) or track not in songs \
            or not isinstance(kind, str) or kind not in EVENTS:
        return None
    timestamp = client_time(item.get("timestamp"))
    if timestamp is None:
        return None
    length = songs[track]
    last = length + PAST_THE_END_S if isinstance(length, (int, float)) and length > 0 else MAX_SECONDS
    event = {"user_id": user, "track_id": track, "event": kind, "client_ts": timestamp}
    for name in ("from_s", "to_s") if kind == "seek" else ("position_s",):
        if not seconds(item.get(name)) or item[name] > last:
            return None
        event[name] = round(float(item[name]), 2)
    return event


def from_allowed_page(request: Request) -> bool:
    """Whether a request comes from where events may: the published site's pages (ORIGINS), the
    page's own server (this one), or no web page at all (the tests). Any other website's pages could
    otherwise send events from their visitors' browsers."""
    origin = request.headers.get("origin")
    return origin is None or origin in ORIGINS or urlsplit(origin).netloc == request.headers.get("host")


def refuse(error: str, status: int) -> JSONResponse:
    return JSONResponse({"error": error}, status_code=status)


def create_app(db_path: Path = DB_PATH, catalog: Path = LIBRARY_DIR / "catalog.json") -> FastAPI:
    app = FastAPI(title="Synopsist", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["POST"], allow_headers=["Content-Type"])
    known = KnownTracks(catalog)
    listeners, requests, connection_events = Limiter(EVENTS_PER_MINUTE), Limiter(REQUESTS_PER_MINUTE), Limiter(CONNECTION_EVENTS_PER_MINUTE)

    def over_the_day(users: set[str]) -> bool:
        since = datetime.now(timezone.utc).date().isoformat() + "T00:00:00.000Z"
        conn = db.connect(db_path)
        try:
            return any(db.events_since(conn, user, since) >= EVENTS_PER_DAY for user in users)
        finally:
            conn.close()

    def store(events: list[dict]) -> None:
        conn = db.connect(db_path)
        try:
            db.save_events(conn, events)
        finally:
            conn.close()

    @app.post("/events")
    async def take_events(request: Request):
        if int(request.headers.get("content-length") or 0) > MAX_BODY_BYTES:
            return refuse("too large", 413)
        if not from_allowed_page(request):
            return refuse("not from the site", 403)
        address = request.client.host if request.client else ""
        if not requests.allow(address):
            return refuse("too many requests", 429)
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            return refuse("too large", 413)
        try:
            payload = json.loads(body)
        except ValueError:
            return refuse("not JSON", 400)
        batch = payload if isinstance(payload, list) else [payload]
        if len(batch) > MAX_BATCH:
            return refuse("too many events", 413)
        if not connection_events.allow(address, len(batch)):
            return refuse("too many events", 429)
        songs = known.get()
        events = [event for event in (clean(item, songs) for item in batch) if event]
        users = {event["user_id"] for event in events}
        per_user = {user: sum(event["user_id"] == user for event in events) for user in users}
        if users and (not all(listeners.allow(user, n) for user, n in per_user.items())
                      or await run_in_threadpool(over_the_day, users)):
            return refuse("too many events", 429)
        if events:
            await run_in_threadpool(store, events)
        return {"stored": len(events), "rejected": len(batch) - len(events)}

    # the page, telling js/listening.js where to send the events
    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    def page():
        html = (PLAYER_DIR / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("</head>", f"  {EVENTS_META}\n</head>", 1))

    # Everything else is the website. Static files support byte-range requests, which browsers need
    # to seek inside a song.
    app.mount("/", StaticFiles(directory=PLAYER_DIR, html=True), name="website")
    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Synopsist website and its listening-event API on this computer.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="0.0.0.0 makes it reachable from other devices on your network")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not (LIBRARY_DIR / "catalog.json").exists():
        sys.exit("No music library yet: run python scripts/build_catalog.py first.")
    print(f"Synopsist is running at http://localhost:{args.port}  (press Ctrl+C to stop)")
    print(f"Listening events go to {DB_PATH}; see them with python scripts/listening_log.py")
    # no access log: it would write down every listener's IP address
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
