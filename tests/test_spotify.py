import json

import pytest

from synopsist.apple_music import match
from synopsist.spotify import album_id, fill_links, parse_embed


def embed_page(name, tracks):
    """Spotify's embed page as it comes, cut down to the part read: its __NEXT_DATA__ JSON."""
    entity = {"type": "album", "name": name,
              "trackList": [{"uri": f"spotify:track:{track_id}", "title": title, "duration": ms} for track_id, title, ms in tracks]}
    data = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    return f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></body></html>'


FIELDS = embed_page("Planetary Fields", [("1H4eDiVaoTab9EAIkaSs2b", "Planetary Fields", 455227),
                                         ("5dRZQwDJ48ygKCvY9y4Fl9", "Planetary Fields (Milestone) - Demo", 195689)])


def test_album_id_from_a_link():
    assert album_id("https://open.spotify.com/album/7AQiXe4ZGj6XxWl2e9LUYx?si=Abc123") == "7AQiXe4ZGj6XxWl2e9LUYx"
    assert album_id("https://open.spotify.com/intl-ja/album/7AQiXe4ZGj6XxWl2e9LUYx") == "7AQiXe4ZGj6XxWl2e9LUYx"
    assert album_id("spotify:album:7AQiXe4ZGj6XxWl2e9LUYx") == "7AQiXe4ZGj6XxWl2e9LUYx"
    with pytest.raises(ValueError):
        album_id("https://open.spotify.com/track/1H4eDiVaoTab9EAIkaSs2b")  # a song's link, not its release's


def test_the_embed_page_gives_the_tracks():
    release = parse_embed(FIELDS, "7AQiXe4ZGj6XxWl2e9LUYx")
    assert release["title"] == "Planetary Fields"
    assert [t["title"] for t in release["tracks"]] == ["Planetary Fields", "Planetary Fields (Milestone) - Demo"]
    assert release["tracks"][0]["length"] == pytest.approx(455.227)
    assert release["tracks"][1]["url"] == "https://open.spotify.com/track/5dRZQwDJ48ygKCvY9y4Fl9"
    assert release["tracks"][1]["number"] == (1, 2)
    with pytest.raises(ValueError):
        parse_embed("<html>a page without the track list</html>", "x")


def test_songs_are_paired_by_title_and_length_and_only_blanks_are_filled():
    release = parse_embed(FIELDS, "7AQiXe4ZGj6XxWl2e9LUYx")
    rows = [{"track_id": "pf-final", "title": "Planetary Fields (Final Ver.)", "spotify_url": ""},
            {"track_id": "pf-milestone", "title": "Planetary Fields (Milestone)", "spotify_url": "https://open.spotify.com/track/typed-in"},
            {"track_id": "unreleased", "title": "Planetary Fields (Unreleased)", "spotify_url": ""}]
    songs = [{"track_id": "pf-final", "title": rows[0]["title"], "length": 455.26},
             {"track_id": "pf-milestone", "title": rows[1]["title"], "length": 195.68},
             {"track_id": "unreleased", "title": rows[2]["title"], "length": 301.0}]
    pairs = match(songs, [release])
    assert set(pairs) == {"pf-final", "pf-milestone"}  # the unreleased one's length matches no track
    assert fill_links(rows, pairs) == 1
    assert rows[0]["spotify_url"] == "https://open.spotify.com/track/1H4eDiVaoTab9EAIkaSs2b"
    assert rows[1]["spotify_url"] == "https://open.spotify.com/track/typed-in"  # kept
    assert rows[2]["spotify_url"] == ""
