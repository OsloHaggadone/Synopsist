"""Synopsist web server: serves the website and its music from player/.

Phase 3 adds the listening-event API here, above the website mount.

Run:  python app/server.py      then open http://localhost:8000
"""

import argparse
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synopsist.config import LIBRARY_DIR, PLAYER_DIR

app = FastAPI(title="Synopsist", docs_url=None, redoc_url=None, openapi_url=None)

# API routes go here, before the website, which answers every other path. Static files support
# byte-range requests, which browsers need to seek inside a song.
app.mount("/", StaticFiles(directory=PLAYER_DIR, html=True), name="website")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Synopsist website on this computer.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="0.0.0.0 makes it reachable from other devices on your network")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not (LIBRARY_DIR / "catalog.json").exists():
        sys.exit("No music library yet: run python scripts/build_catalog.py first.")
    print(f"Synopsist is running at http://localhost:{args.port}  (press Ctrl+C to stop)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
