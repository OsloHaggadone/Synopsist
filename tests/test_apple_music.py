from synopsist.apple_music import album_releases, fill_catalog, match, title_similarity


def release(release_id, title, date, tracks):
    return {"id": release_id, "title": title, "date": date, "artwork": f"https://art.example/{release_id}.jpg",
            "tracks": [{"title": name, "number": (1, n), "length": length, "date": date,
                        "url": f"https://music.apple.com/ca/album/x/{release_id}?i={release_id}{n}"}
                       for n, name, length in tracks]}


RELEASES = [
    release(1, "Beyond", "2024-10-06", [(1, "Volition", 226.7), (2, "Jiggly Cake", 123.9), (3, "Journey", 123.9),
                                        (4, "You know what that means...!", 59.1)]),
    release(2, "Planetary Fields - Single", "2024-07-07", [(1, "Planetary Fields", 455.2),
                                                           (2, "Planetary Fields (Milestone) [Demo]", 195.7)]),
    release(3, "Eternal Synopsis - Single", "2026-04-30", [(1, "Eternal Synopsis", 133.3)]),
]


def row(track_id, title, folder, **extra):
    return {"track_id": track_id, "title": title, "album": folder, "release_date": "", "file": f"{folder}/{title}.mp3",
            "spotify_url": "", "apple_music_url": "", "amazon_music_url": ""} | extra


def catalog():
    return [
        row("jiggly-cake", "Jiggly Cake", "Beyond"),
        row("journey", "Journey", "Beyond"),
        row("volition", "Volition", "Beyond", release_date="2024-10-01"),  # typed in by hand
        row("ywtm", "You know what that means... !", "Beyond"),
        row("pf-final", "Planetary Fields (Final Ver.)", "Fields"),
        row("pf-milestone", "Planetary Fields (Milestone)", "Fields"),
        row("ephemeral", "Ephemeral Synopsis", "Dread"),
        row("eternal", "Eternal Synopsis", "Dread"),
    ]


LENGTHS = {"jiggly-cake": 123.89, "journey": 123.89, "volition": 226.68, "ywtm": 59.08, "pf-final": 455.26,
           "pf-milestone": 195.68, "ephemeral": 240.04, "eternal": 133.34}


def songs(rows, lengths=LENGTHS):
    return [{"track_id": r["track_id"], "title": r["title"], "length": lengths.get(r["track_id"])} for r in rows]


def test_title_similarity():
    assert title_similarity("Tropical Space (Day)", "Tropical Space Day") == 1.0
    assert title_similarity("You know what that means... !", "You know what that means...!") == 1.0
    assert title_similarity("Jiggly Cake", "Journey") == 0.0


def test_pairs_by_title_and_length():
    pairs = match(songs(catalog()), RELEASES)
    titles = {track_id: track["title"] for track_id, (_, track) in pairs.items()}
    assert titles == {
        "jiggly-cake": "Jiggly Cake",  # same length as Journey: the title decides
        "journey": "Journey",
        "volition": "Volition",
        "ywtm": "You know what that means...!",
        "pf-final": "Planetary Fields",
        "pf-milestone": "Planetary Fields (Milestone) [Demo]",
        "eternal": "Eternal Synopsis",
    }  # Ephemeral Synopsis isn't released: a similar title alone isn't enough


def test_without_lengths_titles_must_be_close():
    pairs = match(songs(catalog(), lengths={}), RELEASES)
    assert "volition" in pairs and "eternal" in pairs
    assert "pf-final" not in pairs and "ephemeral" not in pairs


def test_fill_catalog_fills_blanks_and_orders_whole_releases():
    rows = catalog()
    pairs = match(songs(rows), RELEASES)
    rows, changes = fill_catalog(rows, pairs)
    by_id = {r["track_id"]: r for r in rows}
    assert by_id["journey"]["release_date"] == "2024-10-06"
    assert by_id["volition"]["release_date"] == "2024-10-01"  # kept
    assert by_id["eternal"]["apple_music_url"].endswith("?i=31")
    assert by_id["ephemeral"]["release_date"] == "" and by_id["ephemeral"]["apple_music_url"] == ""
    assert (changes["release_date"], changes["apple_music_url"]) == (6, 7)
    # Beyond is exactly one release, so it takes the official order; Dread is only partly released
    assert [r["track_id"] for r in rows] == ["volition", "jiggly-cake", "journey", "ywtm", "pf-final", "pf-milestone",
                                             "ephemeral", "eternal"]
    assert changes["reordered"] == ["Beyond"]


def test_only_whole_releases_give_covers():
    rows = catalog()
    exact = album_releases(rows, match(songs(rows), RELEASES))
    assert {folder: r["title"] for folder, r in exact.items()} == {"Beyond": "Beyond", "Fields": "Planetary Fields - Single"}


def test_keep_order():
    rows = catalog()
    rows, changes = fill_catalog(rows, match(songs(rows), RELEASES), reorder=False)
    assert rows[0]["track_id"] == "jiggly-cake" and changes["reordered"] == []
