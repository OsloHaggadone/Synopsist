import csv

import pytest

from synopsist import db
from synopsist.ingest import CatalogError, cover_image, register_tracks, slugify, sync_catalog


@pytest.fixture
def stream(tmp_path):
    root = tmp_path / "stream"
    for name in ["Album A/Song One.mp3", "Album A/Song (One).mp3", "Album B/Café.mp3", "Album B/夜.mp3",
                 "Album B/LOUD.MP3", "Album B/notes.txt", "Album B/cover.jpg", "loose.mp3",
                 "Album C/Disc 1/deep.mp3", ".hidden/x.mp3"]:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(b"")
    return root


def read(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_slugify():
    assert slugify("Planetary Fields (Final Ver.)") == "planetary-fields-final-ver"
    assert slugify("You know what that means... !") == "you-know-what-that-means"
    assert slugify("Café") == "cafe"
    assert slugify("夜") == ""


def test_first_sync(stream, tmp_path, capsys):
    catalog = tmp_path / "catalog.csv"
    rows = sync_catalog(stream, catalog)
    skipped = [line for line in capsys.readouterr().out.splitlines() if line.startswith("Skipped")]
    assert sorted(skipped) == sorted(f"Skipped (not an .mp3 inside an album folder): {name}" for name in
                                     ["Album B/notes.txt", "Album C/Disc 1/deep.mp3", "loose.mp3"])  # not cover.jpg
    assert {r["file"]: r["track_id"] for r in rows} == {
        "Album A/Song (One).mp3": "song-one",
        "Album A/Song One.mp3": "song-one-2",
        "Album B/Café.mp3": "cafe",
        "Album B/LOUD.MP3": "loud",
        "Album B/夜.mp3": "track",
    }
    assert read(catalog) == rows
    assert rows[2] == {"track_id": "cafe", "title": "Café", "artist": "Oslo Haggadone", "album": "Album B", "release_date": "",
                       "file": "Album B/Café.mp3", "spotify_url": "", "apple_music_url": "", "amazon_music_url": ""}


def test_sync_is_idempotent(stream, tmp_path):
    catalog = tmp_path / "catalog.csv"
    sync_catalog(stream, catalog)
    before = catalog.read_bytes()
    sync_catalog(stream, catalog)
    assert catalog.read_bytes() == before


def test_hand_edits_survive_a_spreadsheet_save(stream, tmp_path):
    catalog = tmp_path / "catalog.csv"
    rows = sync_catalog(stream, catalog)
    for row in rows:
        row["notes"] = ""  # a column added by hand
        if row["track_id"] == "cafe":
            row |= {"title": "Café, Revisited", "artist": "Oslo Haggadone & Someone", "release_date": "2023-05-01",
                    "spotify_url": "https://x", "notes": "hi"}
    with catalog.open("w", newline="", encoding="utf-8-sig") as f:  # BOM and CRLF, like Excel
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (stream / "Album A/Zeta.mp3").write_bytes(b"")

    rows = sync_catalog(stream, catalog)
    assert [r["track_id"] for r in rows] == ["song-one", "song-one-2", "zeta", "cafe", "loud", "track"]
    cafe = next(r for r in rows if r["track_id"] == "cafe")
    assert cafe == {"track_id": "cafe", "title": "Café, Revisited", "artist": "Oslo Haggadone & Someone", "album": "Album B",
                    "release_date": "2023-05-01",
                    "file": "Album B/Café.mp3", "spotify_url": "https://x", "apple_music_url": "", "amazon_music_url": "",
                    "notes": "hi"}
    assert not catalog.read_bytes().startswith(b"\xef\xbb\xbf")


def test_renamed_file_blocks_sync_until_fixed(stream, tmp_path):
    catalog = tmp_path / "catalog.csv"
    sync_catalog(stream, catalog)
    before = catalog.read_bytes()
    (stream / "Album B/Café.mp3").rename(stream / "Album B/Cafe (Remix).mp3")

    with pytest.raises(CatalogError, match="cafe: Album B/Café.mp3"):
        sync_catalog(stream, catalog)
    assert catalog.read_bytes() == before

    catalog.write_text(catalog.read_text(encoding="utf-8").replace("Album B/Café.mp3", "Album B/Cafe (Remix).mp3"),
                       encoding="utf-8")
    rows = sync_catalog(stream, catalog)
    assert next(r for r in rows if r["file"] == "Album B/Cafe (Remix).mp3")["track_id"] == "cafe"


def test_register_tracks(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    rows = [{"track_id": "a", "title": "A", "album": "X", "release_date": "", "file": "X/A.mp3"},
            {"track_id": "b", "title": "B", "album": "X", "release_date": "2024-01-02", "file": "X/B.mp3",
             "spotify_url": "https://open.spotify.com/track/1"},
            {"track_id": "c", "title": "C", "album": "Y", "release_date": "", "file": "Y/C.mp3"}]
    assert register_tracks(conn, rows) == []
    # track numbers follow the catalog's row order within each album
    assert [tuple(r) for r in conn.execute("SELECT track_id, track_no, spotify_url FROM tracks ORDER BY track_id")] == [
        ("a", 1, None), ("b", 2, "https://open.spotify.com/track/1"), ("c", 1, None)]
    rows[0]["title"] = "A (fixed)"
    assert register_tracks(conn, [rows[1], rows[0]]) == ["c"]
    assert [tuple(r) for r in conn.execute("SELECT track_id, title, release_date, track_no FROM tracks ORDER BY track_id")] == [
        ("a", "A (fixed)", None, 2), ("b", "B", "2024-01-02", 1)]


def test_cover_image(tmp_path):
    assert cover_image(tmp_path) is None
    (tmp_path / "Cover.PNG").write_bytes(b"")
    assert cover_image(tmp_path).name == "Cover.PNG"
