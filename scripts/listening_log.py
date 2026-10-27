"""What the event API has stored (data/synopsist.db), to check that listening lands as it should.

Run:  python scripts/listening_log.py              the latest 40 events
      python scripts/listening_log.py --last 200   more of them
      python scripts/listening_log.py --replays    every jump back within a song: from where, to where

Listeners show as the first characters of their random ID.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synopsist import db, events  # noqa: E402
from synopsist.config import DB_PATH  # noqa: E402


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
    args = parser.parse_args()
    if not DB_PATH.exists():
        print("No database yet: run python scripts/build_catalog.py, then python app/server.py and listen a little.")
        return 1
    conn = db.connect()
    total = events.totals(conn)
    print(f"{total['events']} events from {total['listeners']} listener(s), about {total['songs']} song(s)\n")
    rows = events.jumps_back(conn) if args.replays else events.recent(conn, args.last)
    if args.replays:
        print("Jumps back within a song (a replay, as the backend will count them later):")
    for row in rows:
        print(describe(row))
    if not rows:
        print("Nothing yet. Play some songs at http://localhost:8000 (python app/server.py), with sharing on.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
