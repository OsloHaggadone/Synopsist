"""Link each song to itself on Spotify (spotify_url in data/catalog.csv), from its release there.

Give it the link of each release on Spotify (on the album or single: ··· → Share → Copy link). It reads
each release's tracks from Spotify's public embed page (no account or key), pairs them with the songs
here by title and length (as import_apple_music.py does with Apple Music), and fills only blank links:
a song on none of those releases (an unreleased one) keeps none. Run it after a release comes out (for
another artist's songs too), then run build_catalog.py: the song's ··· menu on the site gets "Listen on
Spotify".

Usage: python scripts/import_spotify.py <release link> [<release link> ...]
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synopsist import apple_music, ingest, spotify
from synopsist.config import DB_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill in each song's Spotify link from its releases on Spotify.")
    parser.add_argument("links", nargs="+", help="the link of each release on Spotify (an album or single)")
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

    releases = []
    for link in args.links:
        try:
            releases.append(spotify.fetch_release(link))
        except (ValueError, OSError) as e:
            print(f"Couldn't read {link}: {e}")
            return 1
    print("; ".join(f"{r['title']} ({len(r['tracks'])} tracks)" for r in releases))

    songs = [{"track_id": r["track_id"], "title": r["title"], "length": lengths.get(r["track_id"])} for r in rows]
    pairs = apple_music.match(songs, releases)
    for row in rows:
        if row["track_id"] in pairs:
            release, track = pairs[row["track_id"]]
            note = "" if track["title"] == row["title"] else f'  (on Spotify as "{track["title"]}")'
            print(f"  {row['title']} -> {release['title']}, track {track['number'][1]}{note}")
    paired = {track["url"] for _, track in pairs.values()}
    unpaired = [track["title"] for release in releases for track in release["tracks"] if track["url"] not in paired]
    if unpaired:
        print("On Spotify but paired with no song here: " + ", ".join(unpaired))

    filled = spotify.fill_links(rows, pairs)
    ingest.write_catalog(rows, columns)
    print(f"Filled {filled} Spotify links.")
    print("Now run: python scripts/build_catalog.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
