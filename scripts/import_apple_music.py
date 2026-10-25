"""Fill in what Apple Music knows about your released songs: release dates, a link to each song on
Apple Music, the official track order, and album covers (saved as data/stream/<album>/cover.jpg).

Only blanks are filled: release dates, links, and covers you set yourself are kept. An album is put
in the official track order, and gets a cover, only when all of its songs are in the same Apple
release. Run it after a release comes out, then run build_catalog.py.

Usage: python scripts/import_apple_music.py [--keep-order]
"""

import argparse
import sqlite3
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synopsist import apple_music, ingest
from synopsist.config import APPLE_MUSIC_ARTIST_ID, APPLE_MUSIC_COUNTRY, DB_PATH, STREAM_DIR


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill in release dates, links, track order, and covers from Apple Music.")
    parser.add_argument("--keep-order", action="store_true", help="don't change the order of songs in albums")
    args = parser.parse_args()

    try:
        rows = ingest.sync_catalog()
    except ingest.CatalogError as e:
        print(e)
        return 1
    columns, _ = ingest.read_catalog()

    # song lengths, where the songs have been analyzed, make the pairing reliable
    lengths = {}
    if DB_PATH.exists():
        with sqlite3.connect(DB_PATH) as conn:
            lengths = dict(conn.execute("SELECT track_id, duration_s FROM tracks WHERE duration_s IS NOT NULL"))

    print(f"Reading Apple Music's catalog for artist {APPLE_MUSIC_ARTIST_ID} ({APPLE_MUSIC_COUNTRY} store)...")
    releases = apple_music.fetch_releases(APPLE_MUSIC_ARTIST_ID, APPLE_MUSIC_COUNTRY)
    print(f"{len(releases)} releases: " + "; ".join(f"{r['title']} ({r['date']})" for r in releases))

    songs = [{"track_id": r["track_id"], "title": r["title"], "length": lengths.get(r["track_id"])} for r in rows]
    pairs = apple_music.match(songs, releases)
    for row in rows:
        if row["track_id"] in pairs:
            release, track = pairs[row["track_id"]]
            note = "" if track["title"] == row["title"] else f'  (on Apple Music as "{track["title"]}")'
            print(f"  {row['title']} -> {release['title']}, track {track['number'][1]}{note}")
    unreleased = [row["title"] for row in rows if row["track_id"] not in pairs]
    if unreleased:
        print("Not on Apple Music: " + ", ".join(unreleased))

    rows, changes = apple_music.fill_catalog(rows, pairs, reorder=not args.keep_order)
    ingest.write_catalog(rows, columns)
    print(f"Filled {changes['release_date']} release dates and {changes['apple_music_url']} Apple Music links.")
    for folder in changes["reordered"]:
        print(f"Put {folder} in its official track order.")

    for folder, release in apple_music.album_releases(rows, pairs).items():
        if ingest.cover_image(STREAM_DIR / folder):
            continue
        tmp = STREAM_DIR / folder / "cover.jpg.part"
        urllib.request.urlretrieve(release["artwork"], tmp)
        tmp.replace(STREAM_DIR / folder / "cover.jpg")
        print(f"Saved the cover of {release['title']} as {folder}/cover.jpg")

    print("Now run: python scripts/build_catalog.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
