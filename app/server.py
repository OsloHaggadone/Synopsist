"""Synopsist web server: the website and its music from player/, and the listening-event API.

POST /events takes the player's raw listening events (CLAUDE.md, "Event format"): one event, or a
list of them, as JSON. It's read whatever the content type says, since the player sends it as
text/plain (a page may send that to another site without asking first, and navigator.sendBeacon
carries it). Each event is checked against what the player sends and stored as it came, in the
events table; the backend works out what counts as a replay later (Phase 5). Nothing about the
request is kept: no IP address, no headers, and no access log, since the privacy note promises that
listening data is linked only to the random ID made in the listener's browser.

Serving the website too, it tells the page where the API is (a meta tag in index.html, read by
player/js/listening.js). The published site will reach it from GitHub Pages once it runs elsewhere
(ROADMAP, Phase 4): that origin is allowed (CORS), and others can be added in SYNOPSIST_ORIGINS.

Run:  python app/server.py      then open http://localhost:8000
"""

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
TOO_OLD = timedelta(days=30)  # events the player held on to longer than this aren't taken
TOO_NEW = timedelta(days=1)  # nor any from a clock this far ahead
ORIGINS = [origin for origin in os.environ.get("SYNOPSIST_ORIGINS", "https://oslohaggadone.github.io").split(",") if origin]
EVENTS_META = '<meta name="synopsist-events" content="events">'


class KnownTracks:
    """The track ids on the website (library/catalog.json), read again whenever it's rebuilt."""

    def __init__(self, catalog: Path):
        self.catalog = catalog
        self.stamp = None
        self.ids = frozenset()

    def get(self) -> frozenset:
        try:
            stamp = self.catalog.stat().st_mtime_ns
        except OSError:
            return self.ids
        if stamp != self.stamp:
            self.ids = frozenset(t["id"] for t in json.loads(self.catalog.read_text(encoding="utf-8"))["tracks"])
            self.stamp = stamp
        return self.ids


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


def clean(item, track_ids: frozenset) -> dict | None:
    """An event as it's stored, or None if it isn't one the player sends."""
    if not isinstance(item, dict):
        return None
    user, track, kind = item.get("user_id"), item.get("track_id"), item.get("event")
    if not (isinstance(user, str) and USER_ID.fullmatch(user)) or track not in track_ids or kind not in EVENTS:
        return None
    timestamp = client_time(item.get("timestamp"))
    if timestamp is None:
        return None
    event = {"user_id": user, "track_id": track, "event": kind, "client_ts": timestamp}
    for name in ("from_s", "to_s") if kind == "seek" else ("position_s",):
        if not seconds(item.get(name)):
            return None
        event[name] = round(float(item[name]), 2)
    return event


def create_app(db_path: Path = DB_PATH, catalog: Path = LIBRARY_DIR / "catalog.json") -> FastAPI:
    app = FastAPI(title="Synopsist", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["POST"], allow_headers=["Content-Type"])
    known = KnownTracks(catalog)

    def store(events: list[dict]) -> None:
        conn = db.connect(db_path)
        try:
            db.save_events(conn, events)
        finally:
            conn.close()

    @app.post("/events")
    async def take_events(request: Request):
        if int(request.headers.get("content-length") or 0) > MAX_BODY_BYTES:
            return JSONResponse({"error": "too large"}, status_code=413)
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            return JSONResponse({"error": "too large"}, status_code=413)
        try:
            payload = json.loads(body)
        except ValueError:
            return JSONResponse({"error": "not JSON"}, status_code=400)
        batch = payload if isinstance(payload, list) else [payload]
        if len(batch) > MAX_BATCH:
            return JSONResponse({"error": "too many events"}, status_code=413)
        track_ids = known.get()
        events = [event for event in (clean(item, track_ids) for item in batch) if event]
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
