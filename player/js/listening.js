// Raw listening events, in the format the backend expects (see "Event format" in CLAUDE.md).
// The player only reports what happened; the backend decides what counts as a replay.
//
// With sharing on (the default, unless the browser sends Global Privacy Control), each event goes to
// the event API (app/server.py, POST /events) with a random ID made in this browser, in batches:
// every few seconds, and at once when the page is hidden or closed (navigator.sendBeacon). Turning
// sharing off deletes the ID and whatever hadn't been sent yet (the privacy note promises this). The
// API is the page's own server when it has one (app/server.py says so in a meta tag), or
// SITE.eventsUrl (site.js) once it runs elsewhere; with neither (GitHub Pages for now, the private
// copy), nothing is sent and no ID is made. With ?debug in the URL, events are printed too.
//
// The first part of the self-check (ROADMAP, Phase 4): a seek or a pause is only recorded once it has
// lasted a few seconds (SETTLE_MS). Seeks closer together than that are one jump, from where the first
// left to where the last landed (holding an arrow key, scrubbing on the lock screen), and a pause
// undone by play within it is neither. Anything else first lets out what was held, so the order
// stays true. The backend checks the same on its side (src/synopsist/events.py, app/server.py).
//
// Events that couldn't be sent (offline, or the page closing without a connection) wait in this
// browser until the next visit, then go; turning sharing off deletes them too.

import { SITE } from "../site.js";

const SHARE_KEY = "synopsist.shareListening";
const ID_KEY = "synopsist.listener";
const SEND_EVERY_MS = 10_000; // a batch goes this long after its first event
const SEND_AT = 25; // or as soon as this many are waiting
const RETRY_MS = 30_000; // after the API couldn't be reached
const KEEP_AT_MOST = 500; // waiting events (the oldest go first while it can't be reached)
const SETTLE_MS = 3000; // how long a seek or a pause has to last to be recorded
const WAITING_KEY = "synopsist.waiting"; // events kept for the next visit
const DEBUG = new URLSearchParams(location.search).has("debug");
const recorded = [];
if (DEBUG) window.synopsistEvents = recorded;

const endpoint = (() => {
  const url = SITE.eventsUrl || document.querySelector('meta[name="synopsist-events"]')?.content;
  return url ? new URL(url, location.href).href : null;
})();
let waiting = []; // events not sent yet
let held = null; // { record, timer }: a seek or a pause, until it has lasted SETTLE_MS
let timer = 0;
let id = null;

function store(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // storage blocked: it lasts until the page is closed
  }
}

function recall(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

// On unless the listener turned it off, or their browser sends Global Privacy Control.
export function sharingEnabled() {
  const choice = recall(SHARE_KEY);
  return choice === null ? !navigator.globalPrivacyControl : choice === "1";
}

export function setSharing(on) {
  store(SHARE_KEY, on ? "1" : "0");
  if (on) return;
  // the ID goes, and so does anything not sent yet
  id = null;
  store(ID_KEY, null);
  store(WAITING_KEY, null);
  waiting = [];
  clearTimeout(held?.timer);
  held = null;
  clearTimeout(timer);
  timer = 0;
}

// The start of this browser's random ID (as scripts/listening_log.py shows listeners), or null
// before it has one: Settings shows it, so a listener can find their own listening.
export function listenerTag() {
  const stored = id ?? recall(ID_KEY);
  return /^anon_[0-9a-f]{32}$/.test(stored ?? "") ? stored.slice(5, 11) : null;
}

// The listener's random ID ("anon_" and 32 hex digits, nothing else in it), made the first time an
// event is to be sent.
function listenerId() {
  id ??= recall(ID_KEY);
  if (!/^anon_[0-9a-f]{32}$/.test(id ?? "")) {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    id = `anon_${[...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("")}`;
    store(ID_KEY, id);
  }
  return id;
}

const round = (seconds) => Math.round(seconds * 10) / 10;

// event: play | pause | seek | skip | ended | position
// fields: { position_s } for every event except seek, which has { from_s, to_s }
export function logEvent(trackId, event, fields) {
  if (!sharingEnabled()) return;
  const record = { user_id: endpoint ? listenerId() : null, track_id: trackId, event, timestamp: new Date().toISOString() };
  for (const [name, value] of Object.entries(fields)) record[name] = round(value);
  const same = held?.record.track_id === trackId;
  if (same && held.record.event === "seek" && event === "seek") {
    held.record.to_s = record.to_s; // one jump, to where this one landed
    settle();
    return;
  }
  if (same && held.record.event === "pause" && event === "play") {
    clearTimeout(held.timer); // paused for a moment only: neither is recorded
    held = null;
    return;
  }
  letOut();
  if (event === "seek" || event === "pause") {
    held = { record };
    settle();
  } else {
    queue(record);
  }
}

function settle() {
  clearTimeout(held.timer);
  held.timer = setTimeout(letOut, SETTLE_MS);
}

function letOut(sending = true) {
  if (!held) return;
  clearTimeout(held.timer);
  const { record } = held;
  held = null;
  queue(record, sending);
}

function queue(record, sending = true) {
  if (DEBUG) {
    recorded.push(record);
    console.log("[listening]", JSON.stringify(record));
  }
  if (!endpoint) return;
  waiting.push(record);
  if (waiting.length > KEEP_AT_MOST) waiting.splice(0, waiting.length - KEEP_AT_MOST);
  if (!sending) return;
  // the page going away (the player notes where it was): sent now, or never
  if (document.visibilityState === "hidden") send(true);
  else if (waiting.length >= SEND_AT) send();
  else if (!timer) timer = setTimeout(send, SEND_EVERY_MS);
}

// The waiting events, in one request. As text/plain, so a page may send it to another site without
// asking first, and a beacon (which outlives the page) can carry it.
function send(leaving = false) {
  clearTimeout(timer);
  timer = 0;
  if (leaving) letOut(false); // the page is going: what was held goes as it is
  if (!waiting.length) return keep();
  if (leaving && navigator.onLine === false) return keep(); // nothing would get through: next visit
  const batch = waiting;
  waiting = [];
  const body = JSON.stringify(batch);
  if (leaving && navigator.sendBeacon?.(endpoint, new Blob([body], { type: "text/plain" }))) return keep();
  fetch(endpoint, { method: "POST", body, headers: { "Content-Type": "text/plain" }, keepalive: body.length < 60_000 })
    .then((response) => {
      if (response.status >= 500) throw new Error(`HTTP ${response.status}`); // (a 4xx won't get better)
      keep();
    })
    .catch(() => {
      if (!sharingEnabled()) return;
      waiting = [...batch, ...waiting].slice(-KEEP_AT_MOST); // tried again later, in order
      keep();
      timer ||= setTimeout(send, RETRY_MS);
    });
}

// What's still waiting, kept in this browser in case the page closes before it gets through.
function keep() {
  store(WAITING_KEY, waiting.length && sharingEnabled() ? JSON.stringify(waiting) : null);
}

if (endpoint) {
  addEventListener("pagehide", () => send(true));
  document.addEventListener("visibilitychange", () => document.visibilityState === "hidden" && send(true));
  addEventListener("online", () => send());
  // what an earlier visit couldn't send
  try {
    const kept = JSON.parse(recall(WAITING_KEY) ?? "[]");
    store(WAITING_KEY, null);
    if (sharingEnabled() && Array.isArray(kept) && kept.length) {
      waiting = kept.slice(-KEEP_AT_MOST);
      timer = setTimeout(send, 2000);
    }
  } catch {
    store(WAITING_KEY, null);
  }
}
