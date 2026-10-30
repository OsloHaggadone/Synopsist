"""Check that every song the website's song list names is in the songs folder, before publishing.

player/library/audio/ is a clone of the private repository OsloHaggadone/synopsist-audio. The site's
publishing (.github/workflows/pages.yml) takes the songs from there and runs this first: a site whose
songs weren't pushed yet is never published (push them first: sh Synopsist/scripts/push_songs.sh).

    python scripts/check_songs.py            # just check
    python scripts/check_songs.py --prune    # the publishing's copy: also remove every file the song
                                             # list doesn't name, so a song taken off the site is never
                                             # published again, whatever the songs repository still has
"""
import json
import sys
from pathlib import Path

LIBRARY = Path(__file__).resolve().parent.parent / "player" / "library"


def main() -> None:
    tracks = json.loads((LIBRARY / "catalog.json").read_text(encoding="utf-8"))["tracks"]
    named = {(LIBRARY / t["src"]).resolve() for t in tracks if "://" not in t["src"]}
    missing = sorted(path.name for path in named if not path.is_file())
    if missing:
        sys.exit(f"{len(missing)} of {len(tracks)} songs aren't in {LIBRARY / 'audio'}: {', '.join(missing)}. "
                 "Push the songs first (sh Synopsist/scripts/push_songs.sh), then publish again.")
    if "--prune" in sys.argv:
        extra = [path for path in (LIBRARY / "audio").iterdir() if path.is_file() and path.resolve() not in named]
        for path in extra:
            path.unlink()
        print(f"Left out {len(extra)} file(s) the song list doesn't name.")
    print(f"All {len(tracks)} songs are there.")


if __name__ == "__main__":
    main()
