// The playback engine: one <audio> element, a play queue, shuffle, and repeat. It knows nothing
// about the page; app.js draws it and listens for its "change" events.
//
// The queue is one list: songs already played, the current song, then what's next. Songs the
// listener queued themselves ("added") play before the rest of the album or list they chose
// (the "context"), like Spotify's queue.

import { logEvent } from "./listening.js";

const RESTART_AFTER_S = 3; // "previous" restarts the current song once it has played this long
const POSITION_EVERY_S = 15; // how often the playhead is reported while playing
const PREFS_KEY = "synopsist.player";

let lastKey = 0;
const entry = (id, added = false) => ({ key: ++lastKey, id, added });

function shuffled(list) {
  const out = list.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

export class Player extends EventTarget {
  constructor({ tracks, albums, artist }) {
    super();
    this.tracks = new Map(tracks.map((t) => [t.id, t]));
    this.albums = new Map(albums.map((a) => [a.id, a]));
    this.artist = artist;
    this.audio = new Audio();
    this.audio.preload = "auto";
    this.items = []; // queue entries: history, the current song, then upcoming
    this.index = -1; // position of the current song in items
    this.contextIds = []; // the album or list being played, in its own order
    this.contextLabel = "";
    this.shuffle = false;
    this.repeat = "off"; // off | all | one
    this.failed = null; // the song that couldn't be loaded, if any
    this._started = false; // whether the current song has played at all
    this.continuing = false; // whether the current song came on by itself, the one before it ended
    this._timer = null;
    this._restorePrefs();
    this._listen();
    this._mediaSessionHandlers();
  }

  // --- state ---------------------------------------------------------------------------------

  get current() {
    const e = this.items[this.index];
    return e ? this.tracks.get(e.id) : null;
  }
  get upcoming() {
    return this.items.slice(this.index + 1);
  }
  get playing() {
    return !this.audio.paused;
  }
  get time() {
    return this.audio.currentTime || 0;
  }
  get duration() {
    const d = this.audio.duration;
    return Number.isFinite(d) && d > 0 ? d : this.current?.duration ?? 0;
  }
  get buffering() {
    return this.playing && this.audio.readyState < 3;
  }

  // --- choosing what plays -------------------------------------------------------------------

  // Play a list of songs (an album, or everything), starting from one of them. With autoplay
  // false the song is only loaded, ready for the listener to press play.
  playList(ids, { start = null, label = "", autoplay = true } = {}) {
    this.continuing = false;
    this._leave();
    const queued = this.upcoming.filter((e) => e.added); // the listener's own queue carries over
    this.contextIds = ids.slice();
    this.contextLabel = label;
    let order = ids.map((id) => entry(id));
    let at = start ? Math.max(0, ids.indexOf(start)) : 0;
    if (this.shuffle) {
      const first = start ? order.splice(at, 1) : [];
      order = [...first, ...shuffled(order)];
      at = 0;
    }
    this.items = [...order.slice(0, at + 1), ...queued, ...order.slice(at + 1)];
    this._load(at, autoplay);
  }

  playNext(id) {
    this._insert(id, this.index + 1);
  }

  addToQueue(id) {
    let at = this.index + 1;
    while (at < this.items.length && this.items[at].added) at++;
    this._insert(id, at);
  }

  remove(key) {
    const at = this.items.findIndex((e) => e.key === key);
    if (at > this.index) {
      this.items.splice(at, 1);
      this._changed("queue");
    }
  }

  // Clear the listener's own queue ("added") or the rest of the album or list ("context").
  clearUpcoming(which) {
    const keep = this.upcoming.filter((e) => (which === "added" ? !e.added : e.added));
    this.items = [...this.items.slice(0, this.index + 1), ...keep];
    this._changed("queue");
  }

  // Play a queued song now; everything else stays queued.
  jump(key) {
    const at = this.items.findIndex((e) => e.key === key);
    if (at <= this.index) return;
    this.continuing = false;
    this._leave();
    const [chosen] = this.items.splice(at, 1);
    this.items.splice(this.index + 1, 0, chosen);
    this._load(this.index + 1, true);
  }

  // --- transport -----------------------------------------------------------------------------

  play() {
    if (!this.current) return;
    this.audio.play().catch((error) => {
      if (error.name !== "AbortError") this._changed("state"); // e.g. autoplay blocked: stay paused
    });
  }

  pause() {
    this.audio.pause();
  }

  toggle() {
    this.playing ? this.pause() : this.play();
  }

  next() {
    if (!this.current) return;
    this.continuing = false;
    this._leave();
    this._advance();
  }

  previous() {
    if (!this.current) return;
    this.continuing = false;
    if (this.time > RESTART_AFTER_S || this.index === 0) {
      this.seek(0);
      if (!this.playing) this.play();
      return;
    }
    this._leave();
    this._load(this.index - 1, true);
  }

  // A jump the listener made: seek bar, arrow keys, lock screen.
  seek(seconds) {
    if (!this.current) return;
    const from = this.time;
    const to = Math.min(Math.max(seconds, 0), Math.max(this.duration - 0.25, 0));
    this.audio.currentTime = to;
    logEvent(this.current.id, "seek", { from_s: from, to_s: to });
    this._changed("time");
  }

  seekBy(delta) {
    this.seek(this.time + delta);
  }

  setShuffle(on) {
    this.shuffle = on;
    if (this.current && this.contextIds.length) {
      const queued = this.upcoming.filter((e) => e.added);
      let rest;
      if (on) {
        // every other song of the album or list, in random order
        const currentId = this.items[this.index].added ? null : this.current.id;
        rest = shuffled(this.contextIds.filter((id) => id !== currentId)).map((id) => entry(id));
      } else {
        // back to the list's own order, continuing after the last song played from it
        rest = this.contextIds.slice(this._contextPosition() + 1).map((id) => entry(id));
      }
      this.items = [...this.items.slice(0, this.index + 1), ...queued, ...rest];
    }
    this._savePrefs();
    this._changed("queue");
  }

  cycleRepeat() {
    this.repeat = { off: "all", all: "one", one: "off" }[this.repeat];
    this._savePrefs();
    this._changed("mode");
  }

  setVolume(volume) {
    this.audio.volume = volume;
    this.audio.muted = volume === 0;
  }

  toggleMute() {
    if (this.audio.muted && this.audio.volume === 0) this.audio.volume = 0.5;
    this.audio.muted = !this.audio.muted;
  }

  // --- internals -----------------------------------------------------------------------------

  _insert(id, at) {
    if (!this.current) {
      // nothing loaded yet: the queue starts with this song, ready to play
      this.items = [entry(id, true)];
      this.contextIds = [];
      this.contextLabel = "";
      this._load(0, false);
      return;
    }
    this.items.splice(at, 0, entry(id, true));
    this._changed("queue");
  }

  _load(index, autoplay) {
    this.index = index;
    const track = this.current;
    this._started = false;
    this.failed = null;
    this.audio.src = track.src;
    this._updateMediaSession(track);
    this._changed("track");
    if (autoplay) this.play();
  }

  // After the current song: the next one, or around again when repeating everything.
  _advance() {
    if (this.index + 1 < this.items.length) {
      this._load(this.index + 1, true);
    } else if (this.repeat === "all") {
      const ids = this.contextIds.length ? this.contextIds : this.items.map((e) => e.id);
      this.items = (this.shuffle ? shuffled(ids) : ids).map((id) => entry(id));
      this._load(0, true);
    } else {
      // end of the queue: stop, ready to play the last song again
      this.audio.pause();
      this.audio.currentTime = 0;
      this._changed("state");
    }
  }

  // The listener is moving on from a song they started but didn't finish.
  _leave() {
    if (this.current && this._started && !this.audio.ended) {
      logEvent(this.current.id, "skip", { position_s: this.time });
    }
  }

  _contextPosition() {
    for (let i = this.index; i >= 0; i--) {
      if (!this.items[i].added) return this.contextIds.indexOf(this.items[i].id);
    }
    return -1;
  }

  _changed(what) {
    this.dispatchEvent(new CustomEvent("change", { detail: what }));
  }

  _listen() {
    const audio = this.audio;
    audio.addEventListener("play", () => {
      this._started = true;
      logEvent(this.current.id, "play", { position_s: this.time });
      clearInterval(this._timer);
      this._timer = setInterval(() => logEvent(this.current.id, "position", { position_s: this.time }),
        POSITION_EVERY_S * 1000);
      this._changed("state");
    });
    audio.addEventListener("pause", () => {
      clearInterval(this._timer);
      if (!audio.ended) logEvent(this.current.id, "pause", { position_s: this.time });
      this._changed("state");
    });
    audio.addEventListener("ended", () => {
      logEvent(this.current.id, "ended", { position_s: this.duration });
      this._started = false;
      this.continuing = true;
      if (this.repeat === "one") {
        audio.currentTime = 0;
        this.play();
      } else {
        this._advance();
      }
    });
    audio.addEventListener("error", () => {
      if (!audio.getAttribute("src") && !audio.src) return;
      this.failed = this.current;
      this._changed("error");
    });
    for (const name of ["timeupdate", "durationchange"]) {
      audio.addEventListener(name, () => {
        this._updatePositionState();
        this._changed("time");
      });
    }
    for (const name of ["waiting", "playing", "canplay"]) audio.addEventListener(name, () => this._changed("state"));
    audio.addEventListener("volumechange", () => {
      this._savePrefs();
      this._changed("volume");
    });
    // where the listener was when they closed the page mid-song
    window.addEventListener("pagehide", () => {
      if (this.playing) logEvent(this.current.id, "position", { position_s: this.time });
    });
  }

  // Lock screen, notification, and media-key controls: play, pause, the next and previous song, and
  // dragging the progress bar. No 10-second skips: iPhones show those in place of next and previous
  // (the user wanted to change songs from the lock screen).
  _mediaSessionHandlers() {
    if (!("mediaSession" in navigator)) return;
    const handlers = {
      play: () => this.play(),
      pause: () => this.pause(),
      previoustrack: () => this.previous(),
      nexttrack: () => this.next(),
      seekto: (details) => this.seek(details.seekTime),
    };
    for (const [action, handler] of Object.entries(handlers)) {
      try {
        navigator.mediaSession.setActionHandler(action, handler);
      } catch {
        // this browser doesn't support that action
      }
    }
  }

  _updateMediaSession(track) {
    if (!("mediaSession" in navigator) || typeof MediaMetadata === "undefined") return;
    const album = this.albums.get(track.album);
    navigator.mediaSession.metadata = new MediaMetadata({
      title: track.title,
      artist: this.artist,
      album: album?.title ?? "",
      artwork: album?.cover ? [{ src: new URL(album.cover, location.href).href, sizes: "640x640", type: "image/jpeg" }] : [],
    });
  }

  _updatePositionState() {
    if (!("mediaSession" in navigator) || !this.duration) return;
    try {
      navigator.mediaSession.setPositionState({
        duration: this.duration,
        playbackRate: this.audio.playbackRate,
        position: Math.min(this.time, this.duration),
      });
    } catch {
      // ignore: not supported, or the duration isn't known yet
    }
  }

  _restorePrefs() {
    try {
      const prefs = JSON.parse(localStorage.getItem(PREFS_KEY) || "{}");
      if (typeof prefs.volume === "number") this.audio.volume = prefs.volume;
      this.audio.muted = Boolean(prefs.muted);
      this.shuffle = Boolean(prefs.shuffle);
      if (["off", "all", "one"].includes(prefs.repeat)) this.repeat = prefs.repeat;
    } catch {
      // no saved preferences
    }
  }

  _savePrefs() {
    try {
      const { volume, muted } = this.audio;
      localStorage.setItem(PREFS_KEY, JSON.stringify({ volume, muted, shuffle: this.shuffle, repeat: this.repeat }));
    } catch {
      // storage blocked: preferences last until the page is closed
    }
  }
}
