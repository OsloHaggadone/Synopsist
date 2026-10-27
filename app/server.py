"""Synopsist web server: the listening-event API, and on this computer the website and its music
from player/ too.

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
- requests from other websites' pages (only the published site's, and the page's own server here);
- more than a listener sends: EVENTS_PER_MINUTE or EVENTS_PER_DAY from one ID, and from one
  connection REQUESTS_PER_MINUTE or CONNECTION_EVENTS_PER_MINUTE. A connection's address is only
  held in memory for that minute, to count with, and never written down;
- anything at all once the disk is nearly full (FULL_DISK), so the database and its backups are safe.

The database is copied once a day while events come in (VACUUM INTO; the newest BACKUPS_KEPT are
kept beside it in backups/), with a warning in the log once the disk is WARN_DISK full. With
SYNOPSIST_ADMIN_TOKEN set, /admin/status says how it's doing and /admin/backup downloads a copy
(scripts/pull_events.py does both): the only way to read the data back out, and only with the token.

Settings, from the environment (the host's are in fly.toml, the token in its secrets):
  SYNOPSIST_DB            where the database is (src/synopsist/config.py)
  SYNOPSIST_CATALOG_URL   the live site's catalog.json: the songs events are taken for, read again
                          every 10 minutes, so a song counts once it's published, without
                          redeploying; without it, player/library/catalog.json here
  SYNOPSIST_WEBSITE=0     the API alone, without the website (on the host: GitHub Pages has that)
  SYNOPSIST_ORIGINS       the sites whose pages may send events (https://oslohaggadone.github.io)
  SYNOPSIST_ADMIN_TOKEN   turns on /admin/

Serving the website too, it tells the page where the API is (a meta tag in index.html, read by
player/js/listening.js); the published site sends to SITE.eventsUrl (site.js).

Run:  python app/server.py      then open http://localhost:8000
"""

import argparse
import json
import logging
import math
import os
import re
import secrets
import shutil
import sys
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
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
EVENTS_PER_DAY = 6000  # in 24 hours (listening around the clock is 5,760 position events)
# One connection, which a household or a dorm may share: a page sends about 6 requests a minute
REQUESTS_PER_MINUTE = 60
CONNECTION_EVENTS_PER_MINUTE = 300
FULL_DISK = 0.95  # past this share of the disk used, nothing more is taken
WARN_DISK = 0.80  # and past this, the log says so
BACKUPS_KEPT = 14  # daily copies
CATALOG_EVERY_S = 10 * 60
ORIGINS = [origin for origin in os.environ.get("SYNOPSIST_ORIGINS", "https://oslohaggadone.github.io").split(",") if origin]
CATALOG_URL = os.environ.get("SYNOPSIST_CATALOG_URL", "")
WEBSITE = os.environ.get("SYNOPSIST_WEBSITE", "1") != "0"
ADMIN_TOKEN = os.environ.get("SYNOPSIST_ADMIN_TOKEN", "")
EVENTS_META = '<meta name="synopsist-events" content="events">'
log = logging.getLogger("uvicorn.error")


class KnownTracks:
    """The songs on the website and their lengths (track id -> seconds), from its catalog.json: the
    live site's when there's a URL (read again every 10 minutes, keeping what it read last when it
    can't be reached), else the file here, read again whenever it's rebuilt."""

    def __init__(self, catalog: Path, url: str = ""):
        self.catalog, self.url = catalog, url
        self.stamp = None
        self.read_at = -math.inf
        self.songs: dict[str, float | None] = {}

    @staticmethod
    def _songs(text: str) -> dict:
        return {track["id"]: track.get("duration") for track in json.loads(text)["tracks"]}

    def get(self) -> dict:
        if self.url:
            if time.monotonic() - self.read_at >= CATALOG_EVERY_S:
                self.read_at = time.monotonic()
                try:
                    with urllib.request.urlopen(self.url, timeout=5) as response:
                        self.songs = self._songs(response.read().decode("utf-8"))
                except (OSError, ValueError, KeyError, TypeError) as error:
                    log.warning("Couldn't read the song list at %s (%s)", self.url, error)
                    if not self.songs:  # nothing to go on yet: again in half a minute
                        self.read_at -= CATALOG_EVERY_S - 30
            if self.songs:
                return self.songs
        try:
            stamp = self.catalog.stat().st_mtime_ns
        except OSError:
            return self.songs
        if stamp != self.stamp:
            self.songs = self._songs(self.catalog.read_text(encoding="utf-8"))
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
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= MAX_SECONDS


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
    if not (isinstance(user, str) and USER_ID.fullmatch(user)) or track not in songs or kind not in EVENTS:
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


def connection(request: Request) -> str:
    """The address a request came from, to count with: on Fly.io its proxy names it, here the socket."""
    return request.headers.get("fly-client-ip") or (request.client.host if request.client else "")


def from_allowed_page(request: Request) -> bool:
    """Whether a request comes from where events may: the published site's pages (ORIGINS), the
    page's own server (app/server.py on this computer), or no web page at all (the tests). Any other
    website's pages could otherwise send events from their visitors' browsers."""
    origin = request.headers.get("origin")
    return origin is None or origin in ORIGINS or urlsplit(origin).netloc == request.headers.get("host")


def disk_used(folder: Path) -> float:
    usage = shutil.disk_usage(folder)
    return usage.used / usage.total


def refuse(error: str, status: int) -> JSONResponse:
    return JSONResponse({"error": error}, status_code=status)


def create_app(db_path: Path = DB_PATH, catalog: Path = LIBRARY_DIR / "catalog.json", *,
               catalog_url: str = CATALOG_URL, website: bool = WEBSITE, admin_token: str = ADMIN_TOKEN) -> FastAPI:
    app = FastAPI(title="Synopsist", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["POST"], allow_headers=["Content-Type"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    backups = db_path.parent / "backups"
    known = KnownTracks(catalog, catalog_url)
    listeners, requests, connection_events = Limiter(EVENTS_PER_MINUTE), Limiter(REQUESTS_PER_MINUTE), Limiter(CONNECTION_EVENTS_PER_MINUTE)
    disk = {"checked": -math.inf, "used": 0.0}
    backing_up = threading.Lock()

    def disk_full() -> bool:
        if time.monotonic() - disk["checked"] > 60:
            disk.update(checked=time.monotonic(), used=disk_used(db_path.parent))
        return disk["used"] >= FULL_DISK

    def over_the_day(users: set[str]) -> bool:
        since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
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

    def back_up_once_a_day() -> None:
        target = backups / f"synopsist-{datetime.now(timezone.utc).date().isoformat()}.db"
        if target.exists() or not backing_up.acquire(blocking=False):
            return
        try:
            backups.mkdir(exist_ok=True)
            partial = target.with_suffix(".partial")
            db.snapshot(db_path, partial)
            partial.replace(target)
            for old in sorted(backups.glob("synopsist-*.db"))[:-BACKUPS_KEPT]:
                old.unlink()
            used = disk_used(db_path.parent)
            if used >= WARN_DISK:
                log.warning("The disk holding %s is %d%% full", db_path, round(used * 100))
        finally:
            backing_up.release()

    @app.post("/events")
    async def take_events(request: Request):
        if int(request.headers.get("content-length") or 0) > MAX_BODY_BYTES:
            return refuse("too large", 413)
        if not from_allowed_page(request):
            return refuse("not from the site", 403)
        address = connection(request)
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
        if await run_in_threadpool(disk_full):
            return refuse("the server's disk is full", 507)
        songs = await run_in_threadpool(known.get)
        events = [event for event in (clean(item, songs) for item in batch) if event]
        users = {event["user_id"] for event in events}
        per_user = {user: sum(event["user_id"] == user for event in events) for user in users}
        if users and (not all(listeners.allow(user, n) for user, n in per_user.items())
                      or await run_in_threadpool(over_the_day, users)):
            return refuse("too many events", 429)
        if events:
            await run_in_threadpool(store, events)
        return JSONResponse({"stored": len(events), "rejected": len(batch) - len(events)},
                            background=BackgroundTask(back_up_once_a_day) if events else None)

    # Reading the data back out: only with the token (not set, these addresses don't exist)
    def admitted(request: Request) -> bool:
        given = request.headers.get("authorization", "").encode()
        return bool(admin_token) and secrets.compare_digest(given, f"Bearer {admin_token}".encode())

    @app.get("/admin/status", include_in_schema=False)
    def status(request: Request):
        if not admitted(request):
            return refuse("not found", 404)
        conn = db.connect(db_path)
        try:
            events, listening, last = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT user_id), MAX(received_at) FROM events").fetchone()
        finally:
            conn.close()
        return {"events": events, "listeners": listening, "last_event": last,
                "disk_used_percent": round(disk_used(db_path.parent) * 100, 1),
                "backups": sorted(path.name for path in backups.glob("synopsist-*.db"))}

    @app.get("/admin/backup", include_in_schema=False)
    def download(request: Request):
        if not admitted(request):
            return refuse("not found", 404)
        backups.mkdir(exist_ok=True)
        copy = backups / f"download-{secrets.token_hex(4)}.db"
        db.snapshot(db_path, copy)
        return FileResponse(copy, media_type="application/vnd.sqlite3", filename="synopsist.db",
                            background=BackgroundTask(copy.unlink, missing_ok=True))

    if not website:
        @app.get("/", include_in_schema=False)
        def about():
            return {"service": "Synopsist's listening API", "events": "POST /events"}

        return app

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
    if not CATALOG_URL and not (LIBRARY_DIR / "catalog.json").exists():
        sys.exit("No music library yet: run python scripts/build_catalog.py first.")
    if WEBSITE:
        print(f"Synopsist is running at http://localhost:{args.port}  (press Ctrl+C to stop)")
    else:
        print(f"Synopsist's listening API is running on port {args.port}")
    print(f"Listening events go to {DB_PATH}; see them with python scripts/listening_log.py")
    # no access log: it would write down every listener's IP address
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
