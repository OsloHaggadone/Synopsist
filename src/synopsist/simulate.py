"""Simulated listening: made-up listeners who listen the way the player reports it, for building and
testing what reads the listening data (replay scores, the artist dashboard, recommendations,
retention) before there are enough real listeners. scripts/simulate_events.py runs it on the real
songs and saves the events in a database of their own (data/simulated.db), never with the real
listening; every simulated listener's ID ends in SIM_MARK, so one can always be told apart.

Each listener has a taste: a couple of moments they love, in the songs' sound (each 4-second
segment's Discogs-EffNet embedding, reduced to TASTE_DIMS directions). From it, how much they like
each song (its moments closest to their taste, ranked against the other songs') and each moment (how
close it is, in standard deviations). Over the weeks they come and listen in sessions: the first on
one of the days the site was shared or any other, most in the evening where they live, and the
keenest come back most. A session is a list (an album from a song they pick, Play all, Shuffle, the
popular order, or a shared song's album) listened down: each song skipped soon or later, more often
the less it's theirs; a jump back to replay a moment close to their taste (a chorus or a full part
most of all), sometimes twice; now and then an intro skipped, a pause, the song from the start again,
a jump back left at once (no replay: the backend's self-check), or a favorite on repeat; and at the
end they close the page mid-song, stay paused, or the list runs out.

What's recorded is what the player sends (js/player.js, js/listening.js): a play, the playhead every
15 s while playing, a seek or a pause only once it has lasted 3 s (let out early by the next event),
a skip or the song's end, the next song's play right after. They're sent in batches, every 30 s or
25 events, at once while the page is hidden (a phone's screen off) or closing, or late, all together,
after listening offline; received_at is when each batch arrives, and what hasn't arrived by `until`
isn't there yet.
"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

TASTE_DIMS = 16
SIM_MARK = "00000000"  # the end of every simulated listener's ID (a real one ends so 1 time in 4 billion)

# the player (js/player.js, js/listening.js)
POSITION_EVERY_S = 15.0
SETTLE_S = 3.0
SEND_EVERY_S = 30.0
SEND_AT = 25
SEND_AT_MOST = 100

# where listeners are, and the hours they listen at, where they are
ZONES = {"America/Los_Angeles": 0.55, "America/New_York": 0.1, "America/Chicago": 0.05, "Asia/Tokyo": 0.08,
         "Asia/Seoul": 0.07, "Asia/Shanghai": 0.05, "Europe/London": 0.05, "Europe/Berlin": 0.05}
HOURS = np.array([3, 2, 1, .5, .3, .3, .6, 1.2, 1.6, 1.4, 1.2, 1.4, 1.8, 1.8, 1.8, 2, 2.4, 2.8, 3.2, 3.8, 4.4,
                  4.8, 4.6, 4.0])
WEEKEND = 1.3  # Fridays to Sundays, against other days
SHARED_DAYS = 3  # days the site was shared, when more new listeners come
REPLAY_CHANCE = 0.035  # of jumping back to a moment as close to the taste as can be, in a song as liked


@dataclass
class Song:
    id: str
    album: str
    duration: float
    starts: np.ndarray  # each segment's start, in seconds
    vectors: np.ndarray  # each segment's sound, a unit vector in the taste space
    fullness: np.ndarray  # each segment's level, 0-1
    chorus: np.ndarray  # whether each segment is in a chorus
    weight: float = 1.0  # how often it's picked: popular songs more, unreleased ones less


@dataclass
class Listener:
    id: str
    zone: str
    taste: np.ndarray
    anchors: list  # (song id, start_s) of the moments the taste came from
    picky: float  # how readily they skip what isn't theirs
    replays: float  # how readily they replay
    patience: float  # songs in a session, on average
    keen: float  # sessions a week
    stay: float  # the chance they come back after each session
    liking: dict = field(default_factory=dict)  # song id -> 0 (least theirs) to 1 (most)
    closeness: dict = field(default_factory=dict)  # song id -> each segment's closeness, in SDs
    sessions: int = 0


def taste_space(embeddings: np.ndarray, dims: int = TASTE_DIMS) -> np.ndarray:
    """Each moment's sound as a unit vector along the embeddings' main directions (PCA)."""
    x = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
    x = x - x.mean(axis=0)
    _, _, vt = np.linalg.svd(x, full_matrices=False)
    reduced = x @ vt[:dims].T
    return reduced / np.linalg.norm(reduced, axis=1, keepdims=True)


def iso(t: float) -> str:
    """A time (seconds since 1970) as the player and the API write it: 2026-11-05T21:14:03.123Z."""
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _pick(rng, weights) -> int:
    weights = np.asarray(weights, dtype=float)
    return int(rng.choice(len(weights), p=weights / weights.sum()))


class Simulation:
    def __init__(self, songs: list[Song], order: list[str], popular: list[str], until: float, days: float, rng):
        self.songs = {song.id: song for song in songs}
        self.order = [song_id for song_id in order if song_id in self.songs]  # the music page's: Play all's
        self.popular = [song_id for song_id in popular if song_id in self.songs]
        self.albums = {}
        for song_id in self.order:
            self.albums.setdefault(self.songs[song_id].album, []).append(song_id)
        self.until, self.start, self.rng = until, until - days * 86400, rng
        self.all_vectors = np.concatenate([song.vectors for song in songs])
        first, last = (datetime.fromtimestamp(t, timezone.utc).date() for t in (self.start, until))
        window = [first + timedelta(d) for d in range((last - first).days + 1)]
        self.shared = sorted(window[i] for i in rng.choice(len(window), size=min(SHARED_DAYS, len(window)), replace=False))

    # --- the listeners ------------------------------------------------------------------------

    def listener(self) -> Listener:
        rng = self.rng
        ids = list(self.songs)
        anchors, vectors = [], []
        for _ in range(int(rng.choice([1, 2, 2, 3]))):
            song = self.songs[ids[_pick(rng, [self.songs[i].weight for i in ids])]]
            seg = _pick(rng, song.fullness ** 2 + 0.15)  # the fuller parts most, a quiet one now and then
            anchors.append((song.id, float(song.starts[seg])))
            vectors.append(song.vectors[seg])
        taste = np.mean(vectors, axis=0) + rng.normal(0, 0.2, TASTE_DIMS)
        taste /= np.linalg.norm(taste)
        zone = list(ZONES)[_pick(rng, list(ZONES.values()))]
        keen = float(np.clip(rng.lognormal(math.log(1.8), 0.8), 0.3, 10))
        who = Listener(
            id=f"anon_{rng.bytes(12).hex()}{SIM_MARK}", zone=zone, taste=taste, anchors=anchors,
            picky=float(rng.uniform(0.5, 1.5)), replays=float(np.clip(rng.lognormal(0, 0.5), 0.3, 3)),
            patience=float(rng.uniform(3, 9)), keen=keen, stay=0.55 + 0.35 * min(1.0, keen / 4))
        sims = self.all_vectors @ taste
        mean, spread = sims.mean(), sims.std()
        scores = {}
        for song in self.songs.values():
            close = song.vectors @ taste
            who.closeness[song.id] = (close - mean) / spread
            scores[song.id] = float(np.sort(close)[-2:].mean())  # its moments closest to the taste
        ranked = sorted(scores, key=scores.get)
        who.liking = {song_id: rank / max(1, len(ranked) - 1) for rank, song_id in enumerate(ranked)}
        return who

    def _moment(self, zone: str, day: date) -> float:
        """A moment on that day where the listener is, at an hour people listen."""
        hour = _pick(self.rng, HOURS)
        local = datetime(day.year, day.month, day.day, hour, int(self.rng.integers(60)), int(self.rng.integers(60)),
                         tzinfo=ZoneInfo(zone))
        return local.timestamp() + float(self.rng.random())

    def visits(self, who: Listener) -> list[float]:
        """When the listener comes: first on a day the site was shared or any other, then back now and
        then, until they stop coming."""
        rng, tz = self.rng, ZoneInfo(who.zone)
        first_day, last_day = (datetime.fromtimestamp(t, tz).date() for t in (self.start, self.until))
        days = [first_day + timedelta(d) for d in range((last_day - first_day).days + 1)]
        for _ in range(20):
            if rng.random() < 0.5:
                day = self.shared[int(rng.integers(len(self.shared)))] + timedelta(int(rng.integers(0, 2)))
            else:
                day = days[_pick(rng, [WEEKEND if d.weekday() >= 4 else 1.0 for d in days])]
            first = self._moment(who.zone, day)
            if self.start <= first < self.until - 600:
                break
        else:
            return []
        times = [first]
        while rng.random() < who.stay:
            later = times[-1] + rng.exponential(7 / who.keen) * 86400
            day = datetime.fromtimestamp(later, tz).date()
            moment = max(self._moment(who.zone, day), times[-1] + 3600 + rng.uniform(0, 3600))
            if moment >= self.until - 600:
                break
            times.append(moment)
        return times

    # --- a session ----------------------------------------------------------------------------

    def _list(self, mode: str, who: Listener) -> list[str]:
        rng = self.rng
        if mode == "all":
            return list(self.order)
        if mode == "shuffle":
            return [self.order[i] for i in rng.permutation(len(self.order))]
        if mode == "popular":
            return self.popular + [song_id for song_id in self.order if song_id not in self.popular]
        # a song they pick (the ones they like, more as they come back), or one shared with them, and
        # its album from there
        knows = min(1.0, 0.3 + 0.25 * who.sessions) if mode == "album" else 0.0
        weights = [self.songs[i].weight * math.exp(3 * knows * (who.liking[i] - 0.5)) for i in self.order]
        song_id = self.order[_pick(rng, weights)]
        album = self.albums[self.songs[song_id].album]
        return album[album.index(song_id):]

    def session(self, who: Listener, start: float) -> tuple[list[tuple], float, bool]:
        """One visit: what the player records, in the order it happens, as (time, song id, event,
        fields); when it ends; and whether the page closed at the end."""
        rng, out = self.rng, []
        mode = ["album", "all", "shuffle", "popular", "link"][_pick(rng, [0.45, 0.15, 0.15, 0.13, 0.12])]
        browsing = mode in ("all", "shuffle", "popular") and rng.random() < 0.35
        queue = self._list(mode, who)
        want = int(rng.geometric(1 / who.patience))
        t, heard, closed = start, 0, False
        while True:
            if not queue:
                if heard >= want:
                    break  # the list ran out
                queue, browsing = self._list("album", who), False
                t += rng.uniform(4, 40)  # picking another song
            song = self.songs[queue.pop(0)]
            heard += 1
            leave = None
            if heard >= want:  # the last one: they close the page partway, stay paused, or hear it out
                ending = rng.random()
                leave = ("close" if ending < 0.55 else "pause" if ending < 0.7 else None)
            how, t = self._listen(who, song, t, out, browsing=browsing, leave=leave)
            while how == "ended" and who.liking[song.id] > 0.85 and rng.random() < 0.05 * who.replays:
                how, t = self._listen(who, song, t + rng.uniform(0.02, 0.06), out)  # on repeat
            if how in ("closed", "left"):
                closed = how == "closed"
                break
            if heard >= want and queue:
                # it ended and the next one came on: they close the page a moment into it
                how, t = self._listen(who, self.songs[queue.pop(0)], t + rng.uniform(0.02, 0.06), out,
                                      leave="close", soon=True)
                closed = True
                break
            if heard >= want:
                break
            t += rng.uniform(0.03, 0.06)  # the next song's play, right after
        who.sessions += 1
        return out, t, closed

    def _listen(self, who: Listener, song: Song, t: float, out: list, *, browsing=False, leave=None, soon=False):
        """One song from its start at time t, recording what the player would; returns how it ended
        ("ended", "skip", "closed": the page closing, "left": paused for good) and when."""
        rng, d = self.rng, song.duration
        like, close = who.liking[song.id], who.closeness[song.id]
        ends = np.append(song.starts[1:], d)

        def record(kind, when, **fields):
            out.append((when, song.id, kind, {name: round(min(max(value, 0.0), d), 1) for name, value in fields.items()}))

        # what this listen holds, in the song's own time
        stops = {}
        if rng.random() < min(0.9, 0.05 + who.picky * 0.75 * (1 - like) ** 2 + (0.25 if browsing else 0)):
            early = rng.random()
            stops["skip"] = (rng.uniform(0.4, 8) if early < 0.35 else rng.uniform(8, 40) if early < 0.65
                             else rng.uniform(0.25, 0.95) * d)
        if leave == "close":
            stops["close"] = rng.uniform(1, 20) if soon else rng.uniform(0.05, 0.95) * d
        if leave == "pause" or rng.random() < 0.05:
            stops["pause"] = rng.uniform(0.1, 0.9) * d
        if rng.random() < 0.04 + 0.1 * (1 - like):
            stops["intro"] = rng.uniform(1.5, 12)  # a jump past the intro
        if rng.random() < 0.015:
            stops["fumble"] = rng.uniform(20, max(21, d - 10))  # a jump back, then off to the next song
        if like > 0.7 and rng.random() < 0.03:
            stops["restart"] = rng.uniform(10, max(11, d - 5))  # "previous" partway: the song again

        record("play", t, position_s=0.0)
        tick = t + POSITION_EVERY_S
        wall, head = t + rng.uniform(0.05, 0.9), 0.0  # the audio starts a moment after the play event
        seg, replays, again, pending = 0, 0, {}, None
        for _ in range(5000):
            next_stops = {kind: at for kind, at in stops.items() if at > head}
            next_stops["segment"] = ends[seg]
            if pending is not None and pending[0] > head:
                next_stops["replay"] = pending[0]
            else:
                pending = None
            kind, at = min(next_stops.items(), key=lambda item: item[1])
            # playing up to it, the playhead reported every 15 s
            stop = wall + (at - head)
            while tick <= stop:
                record("position", tick, position_s=head + max(0.0, tick - wall))
                tick += POSITION_EVERY_S
            wall, head = stop, at
            if kind == "segment":
                if seg + 1 >= len(song.starts) or head >= d - 1e-6:
                    record("ended", wall, position_s=d)
                    return "ended", wall
                # the moment just heard: back to it again?
                z = close[seg]
                chance = (who.replays * REPLAY_CHANCE / (1 + math.exp(-3 * (z - 1.8))) * (1.7 if song.chorus[seg] else 1.0)
                          * (0.5 + song.fullness[seg]) * (0.3 + like))
                if pending is None and replays < 3 and again.get(seg, 0) < 2 and rng.random() < chance:
                    back = float(rng.choice([0.0, 0.0, 4.0, 8.0, 12.0])) + rng.uniform(-1.0, 1.0)
                    pending = (min(head + rng.uniform(0.3, 3.5), d - 0.5), max(0.0, float(song.starts[seg]) - back), seg)
                seg += 1
                continue
            if kind == "replay":
                _, to, moment = pending
                record("seek", wall, from_s=head, to_s=to)
                again[moment] = again.get(moment, 0) + 1
                replays, pending, head = replays + 1, None, to
            elif kind == "skip":
                record("skip", wall, position_s=head)
                return "skip", wall
            elif kind == "close":
                record("position", wall, position_s=head)  # the page closing says where it was
                return "closed", wall
            elif kind == "pause":
                del stops["pause"]
                record("pause", wall, position_s=head)
                length = float(np.clip(rng.lognormal(math.log(45), 1.3), SETTLE_S + 0.5, 3 * 3600))
                if leave == "pause" or (length > 25 * 60 and rng.random() < 0.6):
                    return "left", wall  # never came back to it
                wall += length
                record("play", wall, position_s=head)
                tick = wall + POSITION_EVERY_S
                wall += rng.uniform(0.02, 0.3)
            elif kind == "intro":
                del stops["intro"]
                to = min(rng.uniform(0.15, 0.5) * d, d - 5)
                if to > head + 5:
                    record("seek", wall, from_s=head, to_s=to)
                    head = to
            elif kind == "fumble":
                del stops["fumble"]
                to = max(0.0, head - rng.uniform(3, 15))
                record("seek", wall, from_s=head, to_s=to)
                head = to
                stops["skip"] = head + rng.uniform(0.5, SETTLE_S - 0.2)  # gone before it settles
            elif kind == "restart":
                del stops["restart"]
                record("seek", wall, from_s=head, to_s=0.0)
                head = 0.0
            seg = max(0, int(np.searchsorted(song.starts, head, side="right")) - 1)
        raise RuntimeError(f"a listen of {song.id} didn't end")  # (never: every loop moves the playhead on)

    # --- sending ------------------------------------------------------------------------------

    def deliver(self, out: list[tuple], closed: bool) -> list[tuple]:
        """When each recorded event reaches the API: (queued, sent, index) for each, as the player
        batches them."""
        rng = self.rng
        queued = []
        for i, (when, _, kind, _) in enumerate(out):
            if kind in ("seek", "pause"):  # held until it has lasted, or let out by the next event
                when = min(when + SETTLE_S, out[i + 1][0]) if i + 1 < len(out) else when + SETTLE_S
            queued.append((when, i))
        queued.sort()
        sent = {}
        how = rng.random()
        if how < 0.03:  # listened offline: all of it once they're back, a hundred a minute
            back = queued[-1][0] + rng.uniform(0.5, 30) * 3600
            for n, (_, i) in enumerate(queued):
                sent[i] = back + (n // SEND_AT_MOST) * 60
        elif how < 0.38:  # the page hidden (a phone's screen off): each at once
            for when, i in queued:
                sent[i] = when
        else:
            batch, timer = [], None
            for when, i in queued:
                if timer is not None and when >= timer:
                    sent.update({j: timer for j in batch})
                    batch, timer = [], None
                batch.append(i)
                timer = timer if timer is not None else when + SEND_EVERY_S
                if len(batch) >= SEND_AT:
                    sent.update({j: when for j in batch})
                    batch, timer = [], None
            if batch:  # the page closing sends what's left at once; otherwise its timer does
                last = queued[-1][0]
                sent.update({j: last if closed else timer for j in batch})
        arrivals = {}
        for i in sorted(sent, key=lambda j: (sent[j], j)):  # one request each send, a moment on the way
            arrivals.setdefault(sent[i], sent[i] + rng.uniform(0.08, 0.6))
        return [(queued_at, arrivals[sent[i]], i) for queued_at, i in queued]


def simulate(songs: list[Song], order: list[str], popular: list[str], *, events: int = 6250, tolerance: int = 50,
             days: float = 21, listeners: int = 40, until: float, seed: int) -> tuple[list[dict], list[Listener]]:
    """About `events` simulated events (within `tolerance`) from about `listeners` listeners over the
    `days` before `until`, in the order they arrive, as the events table stores them; and the
    listeners who sent them."""
    rng = np.random.default_rng(seed)
    world = Simulation(songs, order, popular, until, days, rng)
    people, visits = [], []  # each visit: (listener, its events as stored)

    def add_listener():
        who = world.listener()
        people.append(who)
        free = world.start
        for start in world.visits(who):
            start = max(start, free + rng.uniform(600, 7200))  # never two visits at once
            if start >= until - 300:
                break
            out, end, closed = world.session(who, start)
            free = end
            rows = []
            for queued_at, arrived, i in world.deliver(out, closed):
                when, song_id, kind, fields = out[i]
                if arrived > until:
                    continue  # not arrived yet
                rows.append({"user_id": who.id, "track_id": song_id, "event": kind,
                             "position_s": fields.get("position_s"), "from_s": fields.get("from_s"),
                             "to_s": fields.get("to_s"), "client_ts": iso(when), "received_at": iso(arrived),
                             "_order": (arrived, queued_at, i)})
            if rows:
                visits.append((who, rows))

    for _ in range(listeners):
        add_listener()
    low, high = events - tolerance, events + tolerance
    total = sum(len(rows) for _, rows in visits)
    while total < low:
        add_listener()
        total = sum(len(rows) for _, rows in visits)
    # too many: visits left out at random, never so many that it falls short
    for k in rng.permutation(len(visits)):
        if total <= high:
            break
        if total - len(visits[k][1]) >= low:
            total -= len(visits[k][1])
            visits[k] = (visits[k][0], [])
    kept = [rows for _, rows in visits if rows]
    stored = sorted((row for rows in kept for row in rows), key=lambda row: row["_order"])
    for row in stored:
        del row["_order"]
    active = {row["user_id"] for row in stored}
    sessions = {}
    for who, rows in visits:
        if rows:
            sessions[who.id] = sessions.get(who.id, 0) + 1
    for who in people:
        who.sessions = sessions.get(who.id, 0)
    return stored, [who for who in people if who.id in active]
