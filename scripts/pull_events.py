"""Download the live site's listening data, to look at on this computer: the events in the API's D1
database on Cloudflare (worker/), exported with wrangler under your Cloudflare login, as data/live.db,
plus a dated copy in data/backups/ (the newest KEEP): the backup kept off Cloudflare, which can
itself put the database back as it was at any moment of the last 7 days (D1 Time Travel).

Run:        python scripts/pull_events.py
            python scripts/pull_events.py --local   the Worker running here (cd worker && npx wrangler dev)
Look at it: ~/.venvs/datasette/bin/datasette data/live.db
            python scripts/listening_log.py --db data/live.db
"""

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synopsist import db, events  # noqa: E402
from synopsist.config import DATA_DIR, ROOT  # noqa: E402

WORKER_DIR = ROOT / "worker"
DATABASE = "synopsist-events"  # worker/wrangler.toml
LIVE = DATA_DIR / "live.db"
BACKUPS = DATA_DIR / "backups"
KEEP = 30
LOCAL_BIN = Path.home() / ".local" / "bin"  # where Node.js was put (npx), if it isn't on the PATH


def main() -> int:
    parser = argparse.ArgumentParser(description="Download the live listening data to data/live.db.")
    parser.add_argument("--local", action="store_true", help="the Worker running on this computer (wrangler dev) instead")
    args = parser.parse_args()
    if not (WORKER_DIR / "node_modules").exists():
        print("First install the Worker's tools: cd worker && npm install")
        return 1
    env = os.environ | {"PATH": f"{LOCAL_BIN}{os.pathsep}{os.environ.get('PATH', '')}"}
    npx = shutil.which("npx", path=env["PATH"])
    if not npx:
        print("Node.js isn't installed (npx wasn't found): see README.md, \"Running the listening API online\".")
        return 1
    with tempfile.TemporaryDirectory() as folder:
        export = Path(folder) / "events.sql"
        result = subprocess.run([npx, "wrangler", "d1", "export", DATABASE, "--local" if args.local else "--remote",
                                 "--table", "events", "--output", str(export)],
                                cwd=WORKER_DIR, env=env, capture_output=True, text=True)
        if result.returncode != 0 or not export.exists():
            print((result.stderr or result.stdout).strip()[-1500:])
            print("\nCouldn't export the live data. Logged in to Cloudflare (cd worker && npx wrangler login)? "
                  "Is the database made and its id in worker/wrangler.toml?")
            return 1
        # A plain SQLite file, the export's table and rows, then this project's own tables and indexes
        partial = LIVE.with_suffix(".partial")
        partial.unlink(missing_ok=True)
        conn = sqlite3.connect(partial)
        conn.executescript(export.read_text(encoding="utf-8"))
        conn.close()
    conn = db.connect(partial)
    total = events.totals(conn)
    last = conn.execute("SELECT MAX(received_at) FROM events").fetchone()[0]
    conn.execute("PRAGMA journal_mode = DELETE")  # one plain file, to copy or open in anything
    conn.close()
    partial.replace(LIVE)
    BACKUPS.mkdir(exist_ok=True)
    shutil.copy2(LIVE, BACKUPS / f"live-{date.today().isoformat()}.db")
    for old in sorted(BACKUPS.glob("live-*.db"))[:-KEEP]:
        old.unlink()

    print(f"{total['events']} events from {total['listeners']} listener(s), about {total['songs']} song(s); "
          f"the latest arrived {last or 'never'}")
    print(f"Saved to {LIVE}, and a copy in {BACKUPS}")
    print(f"Look at it: ~/.venvs/datasette/bin/datasette {LIVE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
