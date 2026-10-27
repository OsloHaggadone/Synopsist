// Synopsist's listening API on Cloudflare Workers: the live site's POST /events (ROADMAP, Phase 4).
//
// It takes the player's raw listening events (CLAUDE.md, "Event format"): one event, or a list of
// them, as JSON, read whatever the content type says (the player sends text/plain, which a page may
// send to another site without asking first, and navigator.sendBeacon carries). Each is checked the
// way app/server.py checks it on this computer (the same cases: test/event-cases.json, run by both
// test suites) and stored as it came in D1, Cloudflare's SQLite database (the EVENTS binding, made by
// migrations/). The backend works out what counts as a replay later, from a copy of it
// (scripts/pull_events.py). Nothing about the request is kept: no address, no headers, and no logs
// (wrangler.toml), since the privacy note promises that listening data is linked only to the random
// ID made in the listener's browser.
//
// What it turns away, so spam isn't stored (with js/listening.js's settling, the self-check so far):
// - events that aren't ones the player sends: a song not on the website (the live site's song list,
//   CATALOG_URL), a moment past the song's end, an ID the player wouldn't make, a time that isn't
//   believable;
// - requests from other websites' pages (only ORIGINS');
// - more than a listener sends: EVENTS_PER_MINUTE or EVENTS_PER_DAY (a UTC day) from one ID, and
//   from one connection REQUESTS_PER_MINUTE or CONNECTION_EVENTS_PER_MINUTE. Each of Cloudflare's
//   servers counts these in its own memory, so they're approximate; an address is never written
//   down, and is forgotten once its minute is over.

const EVENTS = new Set(["play", "pause", "seek", "skip", "ended", "position"]);
const USER_ID = /^anon_[0-9a-f]{32}$/; // js/listening.js: "anon_" and 16 random bytes
const ISO_TIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:?\d{2})$/;
const MAX_BODY_BYTES = 64 * 1024;
const MAX_BATCH = 500; // events in one request
const MAX_SECONDS = 6 * 60 * 60; // a playhead past this isn't in any song
const PAST_THE_END_S = 2; // nor one this far past the song's length (the player rounds; a little slack)
const TOO_OLD_MS = 30 * 86_400_000; // events the player held on to longer than this aren't taken
const TOO_NEW_MS = 86_400_000; // nor any from a clock this far ahead
// How much one listener sends: about 5 events a minute (the position every 15 s, and what they press)
const EVENTS_PER_MINUTE = 120;
const EVENTS_PER_DAY = 6000; // in a UTC day (listening around the clock is 5,760 position events)
// One connection, which a household or a dorm may share: a page sends a request every 30 s or so
const REQUESTS_PER_MINUTE = 60;
const CONNECTION_EVENTS_PER_MINUTE = 300;
const CATALOG_EVERY_MS = 10 * 60_000;

// One statement for the whole batch, whatever its size (D1 takes at most 100 values per statement)
const INSERT = `INSERT INTO events (user_id, track_id, event, position_s, from_s, to_s, client_ts)
  SELECT json_extract(value, '$.user_id'), json_extract(value, '$.track_id'), json_extract(value, '$.event'),
         json_extract(value, '$.position_s'), json_extract(value, '$.from_s'), json_extract(value, '$.to_s'),
         json_extract(value, '$.client_ts')
  FROM json_each(?)`;

// How much each key (a listener's ID, or a connection's address) sent in the last minute
class Limiter {
  constructor(perMinute) {
    this.perMinute = perMinute;
    this.sent = new Map();
  }

  allow(key, amount = 1) {
    const now = Date.now();
    if (this.sent.size > 10_000) {
      for (const [k, window] of this.sent) if (!window.length || window.at(-1)[0] <= now - 60_000) this.sent.delete(k);
    }
    let window = this.sent.get(key);
    if (!window) this.sent.set(key, (window = []));
    while (window.length && window[0][0] <= now - 60_000) window.shift();
    if (window.reduce((sum, [, n]) => sum + n, 0) + amount > this.perMinute) return false;
    window.push([now, amount]);
    return true;
  }
}

const listeners = new Limiter(EVENTS_PER_MINUTE);
const requests = new Limiter(REQUESTS_PER_MINUTE);
const connectionEvents = new Limiter(CONNECTION_EVENTS_PER_MINUTE);
const today = { day: "", counts: new Map() }; // events per listener today
const catalog = { songs: null, readAt: 0 };

function withinTheDay(perUser) {
  const day = new Date().toISOString().slice(0, 10);
  if (today.day !== day) {
    today.day = day;
    today.counts.clear();
  }
  if ([...perUser].some(([user, n]) => (today.counts.get(user) ?? 0) + n > EVENTS_PER_DAY)) return false;
  for (const [user, n] of perUser) today.counts.set(user, (today.counts.get(user) ?? 0) + n);
  return true;
}

// The songs on the website and their lengths (track id -> seconds, or null), from its catalog.json:
// read again every 10 minutes, keeping what was read last when it can't be reached. SONGS (the same
// JSON) stands in for it in the tests.
function songMap(data) {
  return new Map(data.tracks.map((track) => [track.id, track.duration ?? null]));
}

async function knownSongs(env) {
  if (env.SONGS) return songMap(JSON.parse(env.SONGS));
  const now = Date.now();
  if (now - catalog.readAt >= (catalog.songs ? CATALOG_EVERY_MS : 30_000)) {
    catalog.readAt = now;
    try {
      const response = await fetch(env.CATALOG_URL, { cf: { cacheTtl: 600, cacheEverything: true } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      catalog.songs = songMap(await response.json());
    } catch {
      // what was read last, if anything (with nothing, the events are asked for again later)
    }
  }
  return catalog.songs;
}

function seconds(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= MAX_SECONDS;
}

// The player's timestamp, in UTC, if it's an ISO 8601 time with a time zone and a believable one
function clientTime(value) {
  if (typeof value !== "string" || value.length > 40 || !ISO_TIME.test(value)) return null;
  const moment = Date.parse(value.replace(" ", "T").replace(/([+-]\d{2})(\d{2})$/, "$1:$2"));
  const now = Date.now();
  if (!Number.isFinite(moment) || moment < now - TOO_OLD_MS || moment > now + TOO_NEW_MS) return null;
  return new Date(moment).toISOString();
}

// An event as it's stored, or null if it isn't one the player sends
function clean(item, songs) {
  if (!item || typeof item !== "object" || Array.isArray(item)) return null;
  const { user_id: user, track_id: track, event: kind } = item;
  if (typeof user !== "string" || !USER_ID.test(user) || typeof track !== "string" || !songs.has(track)
      || typeof kind !== "string" || !EVENTS.has(kind)) return null;
  const timestamp = clientTime(item.timestamp);
  if (!timestamp) return null;
  const length = songs.get(track);
  const last = typeof length === "number" && length > 0 ? length + PAST_THE_END_S : MAX_SECONDS;
  const event = { user_id: user, track_id: track, event: kind, client_ts: timestamp };
  for (const name of kind === "seek" ? ["from_s", "to_s"] : ["position_s"]) {
    const value = item[name];
    if (!seconds(value) || value > last) return null;
    event[name] = Math.round(value * 100) / 100;
  }
  return event;
}

function allowedOrigins(env) {
  return (env.ORIGINS ?? "").split(",").map((origin) => origin.trim()).filter(Boolean);
}

// Whether a request comes from where events may: the published site's pages (ORIGINS), the API's
// own address, or no web page at all (the tests). Any other website's pages could otherwise send
// events from their visitors' browsers.
function fromAllowedPage(request, url, env) {
  const origin = request.headers.get("Origin");
  if (origin === null || allowedOrigins(env).includes(origin)) return true;
  try {
    return new URL(origin).host === url.host;
  } catch {
    return false; // "null": a page opened from a file
  }
}

function cors(request, env) {
  const origin = request.headers.get("Origin");
  return origin && allowedOrigins(env).includes(origin) ? { "Access-Control-Allow-Origin": origin, Vary: "Origin" } : { Vary: "Origin" };
}

function answer(body, status, request, env) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...cors(request, env) } });
}

async function takeEvents(request, url, env) {
  const refuse = (error, status) => answer({ error }, status, request, env);
  if (Number(request.headers.get("Content-Length") ?? 0) > MAX_BODY_BYTES) return refuse("too large", 413);
  if (!fromAllowedPage(request, url, env)) return refuse("not from the site", 403);
  const address = request.headers.get("CF-Connecting-IP") ?? "";
  if (!requests.allow(address)) return refuse("too many requests", 429);
  const body = await request.arrayBuffer();
  if (body.byteLength > MAX_BODY_BYTES) return refuse("too large", 413);
  let payload;
  try {
    payload = JSON.parse(new TextDecoder().decode(body));
  } catch {
    return refuse("not JSON", 400);
  }
  const batch = Array.isArray(payload) ? payload : [payload];
  if (batch.length > MAX_BATCH) return refuse("too many events", 413);
  if (!connectionEvents.allow(address, batch.length)) return refuse("too many events", 429);
  const songs = await knownSongs(env);
  if (!songs) return refuse("can't check the songs right now", 503); // the player tries again later
  const events = batch.map((item) => clean(item, songs)).filter(Boolean);
  const perUser = new Map();
  for (const { user_id: user } of events) perUser.set(user, (perUser.get(user) ?? 0) + 1);
  if (perUser.size && (![...perUser].every(([user, n]) => listeners.allow(user, n)) || !withinTheDay(perUser))) {
    return refuse("too many events", 429);
  }
  if (events.length) {
    try {
      await env.EVENTS.prepare(INSERT).bind(JSON.stringify(events)).run();
    } catch {
      return refuse("couldn't store them right now", 503); // (D1's daily limit, say): tried again later
    }
  }
  return answer({ stored: events.length, rejected: batch.length - events.length }, 200, request, env);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/" && request.method === "GET") {
      return answer({ service: "Synopsist's listening API", events: "POST /events" }, 200, request, env);
    }
    if (url.pathname !== "/events") return answer({ error: "not found" }, 404, request, env);
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: { ...cors(request, env), "Access-Control-Allow-Methods": "POST",
        "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "86400" } });
    }
    if (request.method !== "POST") return answer({ error: "POST only" }, 405, request, env);
    return takeEvents(request, url, env);
  },
};
