"""Get songs into Synopsist: keep data/catalog.csv in sync with the MP3s, then register them in the
database.

Each new MP3 in data/stream/<album>/ gets a catalog row: a track_id made from its file name, a title
from its file name, and an album from its folder name. Existing rows keep their values, so hand
edits (release dates, title fixes, links, row order) survive, and a track_id never changes once
assigned, because events are logged against it. The order of an album's rows is its track order on
the website. An album folder can also hold its cover art as cover.jpg (or .png / .webp).
"""

import csv
import hashlib
import re
import sqlite3
import unicodedata
from pathlib import Path

from synopsist.config import ARTIST, CATALOG_CSV, STREAM_DIR

COLUMNS = ["track_id", "title", "artist", "album", "release_date", "file", "spotify_url", "apple_music_url", "amazon_music_url"]
COVER_NAMES = {f"{stem}.{ext}" for stem in ("cover", "folder") for ext in ("jpg", "jpeg", "png", "webp")}


class CatalogError(Exception):
    """The catalog and the files disagree in a way only a person can resolve."""


def slugify(text: str) -> str:
    """'Planetary Fields (Final Ver.)' -> 'planetary-fields-final-ver'"""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def read_catalog(catalog: Path = CATALOG_CSV) -> tuple[list[str], list[dict]]:
    """Return the column names (including any added by hand) and the rows."""
    if not catalog.exists():
        return COLUMNS, []
    # utf-8-sig drops the byte-order mark that spreadsheet apps add when saving CSV
    with catalog.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    extra = [c for c in reader.fieldnames or [] if c not in COLUMNS]
    return COLUMNS + extra, rows


def find_stream_files(stream_dir: Path = STREAM_DIR) -> list[str]:
    """Paths relative to stream_dir, like 'Hollow Journey/Bad Boy.mp3'."""
    files = []
    for path in sorted(stream_dir.rglob("*")):
        rel = path.relative_to(stream_dir)
        if not path.is_file() or any(part.startswith(".") for part in rel.parts):
            continue
        if len(rel.parts) == 2 and path.suffix.lower() == ".mp3":
            files.append(rel.as_posix())
        elif not (len(rel.parts) == 2 and path.name.lower() in COVER_NAMES):
            print(f"Skipped (not an .mp3 inside an album folder): {rel.as_posix()}")
    return files


def cover_image(album_dir: Path) -> Path | None:
    """The album's cover art file, if its folder has one."""
    for path in sorted(album_dir.iterdir()) if album_dir.is_dir() else []:
        if path.name.lower() in COVER_NAMES:
            return path
    return None


def sync_catalog(stream_dir: Path = STREAM_DIR, catalog: Path = CATALOG_CSV) -> list[dict]:
    """Add rows for new MP3s to the catalog and return all rows.

    Raises CatalogError, without writing anything, if a cataloged file has disappeared (renamed,
    moved, or deleted): its row must be fixed by hand so the song keeps its track_id.
    """
    if not stream_dir.is_dir():
        raise CatalogError(f"{stream_dir} not found")
    columns, rows = read_catalog(catalog)
    files = find_stream_files(stream_dir)

    on_disk = set(files)
    cataloged = {row["file"] for row in rows}
    new_files = [file for file in files if file not in cataloged]
    missing = [row for row in rows if row["file"] not in on_disk]
    if missing:
        lines = ["Catalog rows whose file no longer exists:"]
        lines += [f"  {row['track_id']}: {row['file']}" for row in missing]
        if new_files:
            lines += ["Files not in the catalog yet:"] + [f"  {file}" for file in new_files]
        lines.append("If a file was renamed or moved, put its new path in that row's file column "
                     "(this keeps its track_id). If a song was removed, delete its row. Then run again.")
        raise CatalogError("\n".join(lines))

    taken = {row["track_id"] for row in rows}
    for file in new_files:
        path = Path(file)
        base = slugify(path.stem) or "track"
        track_id, n = base, 2
        while track_id in taken:
            track_id, n = f"{base}-{n}", n + 1
        taken.add(track_id)
        rows.append(dict.fromkeys(columns, "") | {"track_id": track_id, "title": path.stem,
                                                    "album": path.parent.name, "file": file})
        print(f"Added {track_id}: {file}")
    for row in rows:  # who each song is by, written out, so it can be changed song by song
        row["artist"] = (row.get("artist") or "").strip() or ARTIST

    rows.sort(key=lambda row: row["album"] or "")  # stable, so the order within an album is kept
    write_catalog(rows, columns, catalog)

    print(f"{len(rows)} songs in {catalog.name}, {len(new_files)} new.")
    undated = [row["track_id"] for row in rows if not row["release_date"]]
    if undated:
        print(f"{len(undated)} have no release_date (fine while they're unreleased).")
    malformed = [row["track_id"] for row in rows
                 if row["release_date"] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["release_date"])]
    if malformed:
        print("release_date is not YYYY-MM-DD for: " + ", ".join(malformed))
    return rows


def write_catalog(rows: list[dict], columns: list[str], catalog: Path = CATALOG_CSV) -> None:
    tmp = catalog.with_suffix(".tmp")  # write a copy first so a failed write can't lose hand edits
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, restval="", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(catalog)


def file_sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def register_tracks(conn: sqlite3.Connection, rows: list[dict]) -> list[str]:
    """Make the tracks table match the catalog: add new songs, update everything the catalog says
    about existing ones, and remove songs no longer in it (with their segments; events are kept).
    Returns the removed track_ids."""
    values, track_no = [], {}
    for row in rows:
        track_no[row["album"]] = track_no.get(row["album"], 0) + 1
        values.append({name: row.get(name) or None for name in COLUMNS} | {"track_no": track_no[row["album"]]})
    columns = COLUMNS + ["track_no"]
    with conn:
        conn.executemany(
            f"""INSERT INTO tracks ({", ".join(columns)}) VALUES ({", ".join(":" + c for c in columns)})
                ON CONFLICT (track_id) DO UPDATE SET
                {", ".join(f"{c} = excluded.{c}" for c in columns if c != "track_id")}""",
            values,
        )
        keep = {row["track_id"] for row in rows}
        removed = [r["track_id"] for r in conn.execute("SELECT track_id FROM tracks")
                   if r["track_id"] not in keep]
        conn.executemany("DELETE FROM tracks WHERE track_id = ?", [(t,) for t in removed])
    return removed
