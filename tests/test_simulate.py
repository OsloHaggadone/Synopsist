"""Simulated listening (src/synopsist/simulate.py), on made-up songs: what it makes is what the player
sends and the API takes, in the amount asked for, marked as simulated, and its replays follow each
listener's taste."""

import re
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from synopsist import db, events, simulate

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from server import clean  # noqa: E402

NOW = time.time()
DAYS = 14


def fake_songs(n=9, seed=0):
    rng = np.random.default_rng(seed)
    songs = []
    for k in range(n):
        duration = round(float(rng.uniform(80, 260)), 2)
        starts = np.arange(0, duration, 4.0)
        vectors = rng.normal(size=(len(starts), simulate.TASTE_DIMS))
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        chorus = (starts > duration * 0.4) & (starts < duration * 0.6)
        songs.append(simulate.Song(f"song-{k}", f"album-{k // 3}", duration, starts, vectors, rng.random(len(starts)), chorus))
    return songs


def run(seed=5, events=2000):
    songs = fake_songs()
    order = [song.id for song in songs]
    rows, people = simulate.simulate(songs, order, order[:3], events=events, tolerance=60, days=DAYS, listeners=15,
                                     until=NOW, seed=seed)
    return songs, rows, people


@pytest.fixture(scope="module")
def made():
    return run()


def seconds(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def test_the_amount_asked_for_over_the_days_asked_for_marked_as_simulated(made):
    _, rows, people = made
    assert 1940 <= len(rows) <= 2060
    assert {row["user_id"] for row in rows} == {who.id for who in people}
    for row in rows:
        assert re.fullmatch(r"anon_[0-9a-f]{32}", row["user_id"]) and row["user_id"].endswith(simulate.SIM_MARK)
        assert NOW - DAYS * 86400 - 1 <= seconds(row["client_ts"]) <= seconds(row["received_at"]) <= NOW
    arrivals = [seconds(row["received_at"]) for row in rows]
    assert arrivals == sorted(arrivals)  # stored in the order they arrive


def test_every_event_is_one_the_api_takes(made):
    songs, rows, _ = made
    lengths = {song.id: song.duration for song in songs}
    for row in rows:
        sent = {"user_id": row["user_id"], "track_id": row["track_id"], "event": row["event"], "timestamp": row["client_ts"]}
        sent |= {name: row[name] for name in ("position_s", "from_s", "to_s") if row[name] is not None}
        assert clean(sent, lengths) is not None, row


def test_listening_reads_like_the_players(made):
    songs, rows, _ = made
    lengths = {song.id: song.duration for song in songs}
    by_listener = {}
    for row in rows:
        by_listener.setdefault(row["user_id"], []).append(row)
    kinds = {row["event"] for row in rows}
    assert kinds == {"play", "position", "seek", "pause", "skip", "ended"}
    for listening in by_listener.values():
        listening.sort(key=lambda row: row["client_ts"])
        playing, last_position = None, None
        for row in listening:
            if row["event"] == "play":
                playing, last_position = row["track_id"], None
                continue
            assert row["track_id"] == playing  # every event comes after its song's play
            if row["event"] == "ended":
                assert row["position_s"] == pytest.approx(lengths[playing], abs=0.06)
            if row["event"] == "position":
                if last_position is not None and last_position["track_id"] == playing:
                    # the playhead every 15 s (or where it was as the page closed)
                    assert seconds(row["client_ts"]) - seconds(last_position["client_ts"]) <= 15.01
                last_position = row
            elif row["event"] in ("pause", "skip", "ended"):
                last_position = None


def test_replays_follow_each_listeners_taste(made, tmp_path):
    songs, rows, people = made
    conn = db.connect(tmp_path / "simulated.db")
    with conn:
        conn.executemany("INSERT INTO events (user_id, track_id, event, position_s, from_s, to_s, client_ts, received_at) "
                         "VALUES (:user_id, :track_id, :event, :position_s, :from_s, :to_s, :client_ts, :received_at)", rows)
    replays = events.jumps_back(conn)
    assert len(replays) >= 10
    who = {person.id: person for person in people}
    by_id = {song.id: song for song in songs}
    rng = np.random.default_rng(1)

    def closest(listener, song, start, end):  # the moment in that stretch closest to the taste
        inside = (by_id[song].starts + 4 > start) & (by_id[song].starts < end)
        return who[listener].closeness[song][inside].max()

    replayed = [closest(r["user_id"], r["track_id"], r["to_s"], r["from_s"]) for r in replays]
    chance = []
    for r in replays:  # stretches as long, anywhere in the same song
        song, length = by_id[r["track_id"]], r["from_s"] - r["to_s"]
        for start in rng.uniform(0, max(0.1, song.duration - length), 50):
            chance.append(closest(r["user_id"], r["track_id"], start, start + length))
    # (about 2.0 against 1.0, in standard deviations)
    assert np.mean(replayed) > np.mean(chance) + 0.6


def test_the_same_seed_makes_the_same_listening():
    assert run(seed=8, events=800)[1] == run(seed=8, events=800)[1]
    assert run(seed=8, events=800)[1] != run(seed=9, events=800)[1]
