"""Download the live site's listening data, to look at on this computer: a copy of the API's database
(app/server.py's /admin/backup) as data/live.db, and a dated copy in data/backups/, which is also
the backup kept off the server (the newest KEEP of them).

First time:  python scripts/pull_events.py --setup https://synopsist-events.fly.dev YOUR-TOKEN
             (where the API is and its admin token, kept in data/live.json: git ignores data/)
Then:        python scripts/pull_events.py
Look at it:  ~/.venvs/datasette/bin/datasette data/live.db
             python scripts/listening_log.py --db data/live.db
"""

import argparse
import json
import shutil
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synopsist.config import DATA_DIR  # noqa: E402

SETTINGS = DATA_DIR / "live.json"
LIVE = DATA_DIR / "live.db"
BACKUPS = DATA_DIR / "backups"
KEEP = 30
SQLITE = b"SQLite format 3\x00"


def ask(settings: dict, path: str):
    request = urllib.request.Request(settings["url"] + path, headers={"Authorization": f"Bearer {settings['token']}"})
    return urllib.request.urlopen(request, timeout=60)  # (a stopped server takes a few seconds to wake)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download the live listening data to data/live.db.")
    parser.add_argument("--setup", nargs=2, metavar=("URL", "TOKEN"), help="where the API is, and its admin token")
    args = parser.parse_args()
    if args.setup:
        DATA_DIR.mkdir(exist_ok=True)
        SETTINGS.write_text(json.dumps({"url": args.setup[0].rstrip("/"), "token": args.setup[1]}), encoding="utf-8")
    if not SETTINGS.exists():
        print("First tell it where the API is: python scripts/pull_events.py --setup URL TOKEN")
        return 1
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    try:
        with ask(settings, "/admin/status") as response:
            status = json.load(response)
        with ask(settings, "/admin/backup") as response:
            data = response.read()
    except urllib.error.HTTPError as error:
        print(f"The API answered {error.code}." + (" Check the URL and the token. A lost token can't be read back"
              " from Fly: set a new one (README.md, \"Running the listening API online\") and run --setup again."
              if error.code == 404 else ""))
        return 1
    except urllib.error.URLError as error:
        print(f"Couldn't reach {settings['url']}: {error.reason}")
        return 1
    if not data.startswith(SQLITE):
        print("What came back isn't a database; nothing was changed.")
        return 1
    partial = LIVE.with_suffix(".partial")
    partial.write_bytes(data)
    partial.replace(LIVE)
    BACKUPS.mkdir(exist_ok=True)
    shutil.copy2(LIVE, BACKUPS / f"live-{date.today().isoformat()}.db")
    for old in sorted(BACKUPS.glob("live-*.db"))[:-KEEP]:
        old.unlink()

    print(f"{status['events']} events from {status['listeners']} listener(s); the latest arrived {status['last_event'] or 'never'}")
    print(f"Saved to {LIVE} ({len(data) / 1e3:.0f} KB), and a copy in {BACKUPS}")
    print(f"The server's disk is {status['disk_used_percent']}% full; it keeps {len(status['backups'])} daily backup(s) of its own")
    if status["disk_used_percent"] >= 80:
        print("That's getting full: see the note on the server's disk in ROADMAP.md (Phase 4).")
    print(f"Look at it: ~/.venvs/datasette/bin/datasette {LIVE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
