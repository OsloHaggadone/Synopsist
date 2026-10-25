"""What Apple Music's public catalog (the iTunes Search API) knows about the released songs in
data/catalog.csv: release dates, song links, the official track order, and album covers.

Catalog songs are paired with Apple tracks by title and length, because titles can differ a little
("Tropical Space (Day)" vs "Tropical Space Day") and two songs can share a length ("Journey" and
"Jiggly Cake" both run 2:03).
"""

import json
import re
import urllib.parse
import urllib.request

LOOKUP_URL = "https://itunes.apple.com/lookup"
MAX_LENGTH_GAP_S = 2.0  # an Apple track and a catalog song this far apart in length can't be the same
MIN_TITLE_SIMILARITY = 0.3  # with matching lengths
MIN_TITLE_SIMILARITY_ALONE = 0.6  # when a song's length isn't known yet (not analyzed)


def _lookup(**params) -> list[dict]:
    with urllib.request.urlopen(f"{LOOKUP_URL}?{urllib.parse.urlencode(params)}", timeout=30) as response:
        return json.load(response)["results"]


def fetch_releases(artist_id: str, country: str) -> list[dict]:
    """Every release by the artist with its tracks, from Apple's public catalog."""
    releases = []
    for album in _lookup(id=artist_id, entity="album", limit=200, country=country):
        if album.get("wrapperType") != "collection":
            continue
        tracks = [t for t in _lookup(id=album["collectionId"], entity="song", limit=200, country=country)
                  if t.get("wrapperType") == "track"]
        releases.append({
            "id": album["collectionId"],
            "title": album["collectionName"],
            "date": album["releaseDate"][:10],
            "artwork": album["artworkUrl100"].replace("100x100bb", "3000x3000bb"),  # full size
            "tracks": [{
                "title": t["trackName"],
                "number": (t.get("discNumber") or 1, t["trackNumber"]),
                "length": t.get("trackTimeMillis", 0) / 1000,
                "date": t["releaseDate"][:10],
                "url": t["trackViewUrl"].split("&")[0],  # drop Apple's tracking parameter
            } for t in tracks],
        })
    return releases


def title_similarity(a: str, b: str) -> float:
    """Share of words the two titles have in common, ignoring case and punctuation."""
    words_a, words_b = set(re.findall(r"[a-z0-9]+", a.lower())), set(re.findall(r"[a-z0-9]+", b.lower()))
    return len(words_a & words_b) / len(words_a | words_b) if words_a | words_b else 0.0


def match(songs: list[dict], releases: list[dict]) -> dict[str, tuple[dict, dict]]:
    """Pair catalog songs ({track_id, title, length or None}) with Apple tracks.
    Returns {track_id: (release, track)}; each track is used once, best pairs first."""
    candidates = []
    for song in songs:
        for release in releases:
            for track in release["tracks"]:
                similarity = title_similarity(song["title"], track["title"])
                if song.get("length") and track["length"]:
                    if abs(song["length"] - track["length"]) > MAX_LENGTH_GAP_S or similarity < MIN_TITLE_SIMILARITY:
                        continue
                    score = similarity + 1
                elif similarity >= MIN_TITLE_SIMILARITY_ALONE:
                    score = similarity
                else:
                    continue
                candidates.append((score, song["track_id"], release["id"], track["url"], release, track))
    pairs, used = {}, set()
    for _, track_id, _, url, release, track in sorted(candidates, key=lambda c: -c[0]):
        if track_id not in pairs and url not in used:
            pairs[track_id] = (release, track)
            used.add(url)
    return pairs


def album_releases(rows: list[dict], pairs: dict) -> dict[str, dict]:
    """Catalog albums that are exactly one Apple release (every song in it paired with a track of
    that release), keyed by album folder. Only those get the release's cover and track order: a
    single that's part of an unreleased album shouldn't give the album its cover."""
    folders = {}
    for row in rows:
        folders.setdefault(row["file"].split("/")[0], []).append(row)
    exact = {}
    for folder, album_rows in folders.items():
        found = {pairs[r["track_id"]][0]["id"] if r["track_id"] in pairs else None for r in album_rows}
        if len(found) == 1 and None not in found:
            exact[folder] = pairs[album_rows[0]["track_id"]][0]
    return exact


def fill_catalog(rows: list[dict], pairs: dict, reorder: bool = True) -> tuple[list[dict], dict]:
    """Fill blank release dates and Apple Music links from the pairs, and put albums that are
    exactly one release in the official track order. Returns the rows and counts of changes."""
    changes = {"release_date": 0, "apple_music_url": 0, "reordered": []}
    for row in rows:
        if row["track_id"] not in pairs:
            continue
        _, track = pairs[row["track_id"]]
        for column, value in (("release_date", track["date"]), ("apple_music_url", track["url"])):
            if not row.get(column):
                row[column] = value
                changes[column] += 1
    if reorder:
        exact = album_releases(rows, pairs)
        folder_of = lambda row: row["file"].split("/")[0]
        position = {row["track_id"]: n for n, row in enumerate(rows)}
        for folder in exact:
            album_rows = [row for row in rows if folder_of(row) == folder]
            official = sorted(album_rows, key=lambda row: pairs[row["track_id"]][1]["number"])
            if official != album_rows:
                slots = sorted(position[row["track_id"]] for row in album_rows)
                for slot, row in zip(slots, official):
                    rows[slot] = row
                changes["reordered"].append(folder)
    return rows, changes
