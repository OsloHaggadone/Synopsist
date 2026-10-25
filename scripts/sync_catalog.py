"""Add new MP3s in data/stream/<album>/ to data/catalog.csv, without analyzing any audio.
build_catalog.py does this as its first step; see synopsist.ingest.sync_catalog for the rules.

Usage: python scripts/sync_catalog.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synopsist.ingest import CatalogError, sync_catalog

if __name__ == "__main__":
    try:
        sync_catalog()
    except CatalogError as e:
        sys.exit(str(e))
