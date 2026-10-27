"""What the event API has stored (data/synopsist.db), to check that listening lands as it should.

Run:  python scripts/listening_log.py              the latest 40 events
      python scripts/listening_log.py --last 200   more of them
      python scripts/listening_log.py --replays    every jump back that counts as a replay (events.py)
      python scripts/listening_log.py --db data/live.db   the live site's, as scripts/pull_events.py
                                                   downloaded it

Listeners show as the first characters of their random ID.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synopsist import db, events  # noqa: E402
from synopsist.config import DB_PATH, LIBRARY_DIR  # noqa: E402


def clock(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    whole = int(seconds)
    return f"{whole // 60}:{whole % 60:02d}.{int(round((seconds - whole) * 10)) % 10}"


def describe(event: dict) -> str:
    where = f"{clock(event['from_s'])} -> {clock(event['to_s'])}" if event["event"] == "seek" else f"at {clock(event['position_s'])}"
    return f"{event['client_ts'][:19].replace('T', ' ')}  {event['user_id'][5:11]}  {event['event']:<8} {where:<17} {event['title']}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the listening events the website has stored.")
    parser.add_argument("--last", type=int, default=40, help="how many of the latest events to show")
    parser.add_argument("--replays", action="store_true", help="show every jump back within a song instead")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="another database, like data/live.db")
    args = parser.parse_args()
    if not args.db.exists():
        print("No database yet: run python scripts/build_catalog.py, then python app/server.py and listen a little."
              if args.db == DB_PATH else f"No database at {args.db}")
        return 1
    conn = db.connect(args.db)
    total = events.totals(conn)
    print(f"{total['events']} events from {total['listeners']} listener(s), about {total['songs']} song(s)\n")
    rows = events.jumps_back(conn) if args.replays else events.recent(conn, args.last)
    # the live database has no songs table: the titles come from the song list here
    try:
        titles = {t["id"]: t["title"] for t in json.loads((LIBRARY_DIR / "catalog.json").read_text(encoding="utf-8"))["tracks"]}
    except OSError:
        titles = {}
    for row in rows:
        row["title"] = titles.get(row["title"], row["title"])
    if args.replays:
        print("Jumps back within a song where the listener stayed (a replay, as the backend will count them):")
    for row in rows:
        print(describe(row))
    if not rows:
        print("Nothing yet. Play some songs at http://localhost:8000 (python app/server.py), with sharing on.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
