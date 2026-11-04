"""What Spotify shows about a release, to link each song to itself on Spotify (spotify_url in
data/catalog.csv). Spotify's API needs a key, so this reads the release's public embed page (the player
a website can embed, open.spotify.com/embed/album/<id>), which carries its track list as JSON: each
track's title, length, and id. If Spotify changes that page, `parse_embed` is the one place to fix.

Songs are paired with Spotify's tracks the way they are with Apple's (apple_music.match: by title and
length, since titles differ a little, like "Planetary Fields (Final Ver.)" and "Planetary Fields"),
and only blank links are filled.
"""

import json
import re
import urllib.request

EMBED_URL = "https://open.spotify.com/embed/album/{}"
TRACK_URL = "https://open.spotify.com/track/{}"
# the embed page is a page for browsers: it comes back as one only when asked like one
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"


def album_id(link: str) -> str:
    """The release's id, from a link to it (an album's or single's ··· → Share → Copy link) or its URI."""
    found = re.search(r"album[/:]([A-Za-z0-9]{22})", link)
    if not found:
        raise ValueError(f"not a link to an album or single on Spotify: {link}")
    return found.group(1)


def parse_embed(html: str, release_id: str) -> dict:
    """A release as apple_music.match takes it: {id, title, tracks: [{title, number, length, url}]}."""
    found = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not found:
        raise ValueError("Spotify's embed page has no track list in it (has the page changed?)")
    entity = json.loads(found.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    tracks = [{"title": track["title"], "number": (1, n), "length": track["duration"] / 1000,
               "url": TRACK_URL.format(track["uri"].rsplit(":", 1)[-1])}
              for n, track in enumerate(entity["trackList"], start=1)]
    return {"id": release_id, "title": entity.get("name") or entity.get("title"), "tracks": tracks}


def fetch_release(link: str) -> dict:
    """The release at a Spotify link, with its tracks."""
    release_id = album_id(link)
    request = urllib.request.Request(EMBED_URL.format(release_id), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return parse_embed(response.read().decode("utf-8"), release_id)


def fill_links(rows: list[dict], pairs: dict) -> int:
    """Fill blank spotify_url cells from the pairs ({track_id: (release, track)}); returns how many.
    A link already there (typed in by hand) is kept."""
    filled = 0
    for row in rows:
        if row["track_id"] in pairs and not row.get("spotify_url"):
            row["spotify_url"] = pairs[row["track_id"]][1]["url"]
            filled += 1
    return filled
