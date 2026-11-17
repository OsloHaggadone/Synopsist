"""Simulated listening data, for building and testing what reads it (replay scores, the artist
dashboard, recommendations, retention) before there are enough real listeners: made-up listeners,
each with a taste of their own, listening to the real songs over the past weeks the way the player
reports it (src/synopsist/simulate.py), saved as data/simulated.db, shaped like the live data's copy
(data/live.db, from scripts/pull_events.py).

It's never the real listening: nothing is sent to the event API or to Cloudflare, data/live.db and
data/synopsist.db aren't touched (the songs' analysis is only read), and every simulated listener's ID
ends in 00000000, so one can always be told apart. data/simulated-truth.json keeps each listener's
taste (the moments it came from) and favorite songs, to check recommendations against
(CLAUDE.md, "Evaluation"). Running it again replaces both.

Run:  python scripts/simulate_events.py                    about 6,250 events over the past 21 days
      python scripts/simulate_events.py --events 10000 --days 28 --seed 7
Look: python scripts/listening_log.py --db data/simulated.db    (--replays: the jumps back that count)
      ~/.venvs/datasette/bin/datasette data/simulated.db
"""

import argparse
import json
import re
import secrets
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synopsist import db, events, simulate  # noqa: E402
from synopsist.config import DATA_DIR, DB_PATH, LIBRARY_DIR, PLAYER_DIR  # noqa: E402

OUT = DATA_DIR / "simulated.db"
TRUTH = DATA_DIR / "simulated-truth.json"


def load_songs() -> tuple[list[simulate.Song], list[str], list[str]]:
    """The songs on the site, with their moments' sound (data/synopsist.db, read only), fullness and
    choruses (their analysis files); the music page's order; and site.js's most popular."""
    catalog = json.loads((LIBRARY_DIR / "catalog.json").read_text(encoding="utf-8"))
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = conn.execute("SELECT track_id, start_s, embedding FROM segments ORDER BY track_id, idx").fetchall()
    conn.close()
    vectors = simulate.taste_space(np.stack([db.from_blob(blob) for _, _, blob in rows]))
    by_song = {}
    for (track_id, start, _), vector in zip(rows, vectors):
        by_song.setdefault(track_id, ([], []))
        by_song[track_id][0].append(start)
        by_song[track_id][1].append(vector)
    site = (PLAYER_DIR / "site.js").read_text(encoding="utf-8")
    popular = re.findall(r'"([\w-]+)"', re.search(r"popular:\s*\[(.*?)\]", site, re.S)[1])
    songs = []
    for track in catalog["tracks"]:
        if track["id"] not in by_song:
            continue
        starts, song_vectors = np.array(by_song[track["id"]][0]), np.stack(by_song[track["id"]][1])
        analysis = json.loads((LIBRARY_DIR / track["analysis"]).read_text(encoding="utf-8")) if track.get("analysis") else {}
        levels = {round(moment["start"]): moment.get("level", 50) for moment in analysis.get("moments", [])}
        fullness = np.array([levels.get(round(start), 50) / 100 for start in starts])
        middles = starts + 2
        chorus = np.array([any(a <= m < b for a, b in analysis.get("chorus", [])) for m in middles])
        rank = popular.index(track["id"]) if track["id"] in popular else None
        weight = (3.0 - 1.5 * rank / max(1, len(popular) - 1)) if rank is not None else 1.0
        if not track.get("release_date"):
            weight *= 0.5  # only on the site, less known
        songs.append(simulate.Song(id=track["id"], album=track["album"], duration=float(track["duration"]),
                                   starts=starts, vectors=song_vectors, fullness=fullness, chorus=chorus, weight=weight))
    order = [song_id for album in catalog["albums"] for song_id in album["tracks"]]
    return songs, order, popular


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate listening, for testing, into data/simulated.db.")
    parser.add_argument("--events", type=int, default=6250, help="about how many events (default 6250)")
    parser.add_argument("--tolerance", type=int, default=50, help="how far off that may land (default 50)")
    parser.add_argument("--days", type=float, default=21, help="over how many days, up to now (default 21)")
    parser.add_argument("--listeners", type=int, default=40, help="about how many listeners (default 40)")
    parser.add_argument("--seed", type=int, help="the same seed (and --until) makes the same listening again")
    parser.add_argument("--until", help="the end of it, an ISO time (default: now)")
    args = parser.parse_args()
    if not DB_PATH.exists() or not (LIBRARY_DIR / "catalog.json").exists():
        print("No songs' analysis yet: run python scripts/build_catalog.py first.")
        return 1
    seed = args.seed if args.seed is not None else secrets.randbelow(100_000)
    until = (datetime.fromisoformat(args.until.replace("Z", "+00:00")) if args.until else datetime.now(timezone.utc)).timestamp()

    songs, order, popular = load_songs()
    rows, listeners = simulate.simulate(songs, order, popular, events=args.events, tolerance=args.tolerance,
                                        days=args.days, listeners=args.listeners, until=until, seed=seed)

    for path in (OUT, OUT.with_name(OUT.name + "-wal"), OUT.with_name(OUT.name + "-shm")):
        path.unlink(missing_ok=True)
    conn = db.connect(OUT)
    with conn:
        conn.executemany("INSERT INTO events (user_id, track_id, event, position_s, from_s, to_s, client_ts, received_at) "
                         "VALUES (:user_id, :track_id, :event, :position_s, :from_s, :to_s, :client_ts, :received_at)", rows)
    replays = events.jumps_back(conn)
    total = events.totals(conn)
    conn.execute("PRAGMA journal_mode = DELETE")  # one plain file, as data/live.db is
    conn.close()

    TRUTH.write_text(json.dumps({
        "about": "Simulated listening (scripts/simulate_events.py): not real listeners. Each one's taste comes from "
                 "the moments in `anchors`; `favorites` are the songs closest to it, most first.",
        "seed": seed, "until": simulate.iso(until), "days": args.days, "events": len(rows),
        "listeners": [{
            "id": who.id, "zone": who.zone, "sessions": who.sessions,
            "anchors": [{"song": song_id, "at_s": at} for song_id, at in who.anchors],
            "favorites": sorted(who.liking, key=who.liking.get, reverse=True)[:5],
            "picky": round(who.picky, 2), "replays": round(who.replays, 2), "keen": round(who.keen, 2),
        } for who in listeners],
    }, indent=2) + "\n", encoding="utf-8")

    kinds = Counter(row["event"] for row in rows)
    first, last = rows[0]["client_ts"][:10], max(row["client_ts"] for row in rows)[:10]
    print(f"{total['events']:,} simulated events from {total['listeners']} listeners, {total['songs']} songs, "
          f"{first} to {last} (seed {seed})")
    print("  " + " · ".join(f"{kind} {kinds[kind]:,}" for kind in ("play", "position", "seek", "pause", "skip", "ended")))
    print(f"  {len(replays)} replays as the backend counts them (jumps back where the listener stayed)")
    print(f"Saved to {OUT}, and each listener's taste in {TRUTH}")
    print(f"Look at it: python scripts/listening_log.py --db {OUT.relative_to(DATA_DIR.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
