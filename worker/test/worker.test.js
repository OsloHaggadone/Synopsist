// The Worker, run on this computer by wrangler's test harness (Cloudflare's own runtime, from
// wrangler.toml, with a D1 database of its own): npm test, in worker/. Each test gets a fresh Worker,
// so its counts start from nothing.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { createTestHarness } from "wrangler";

const folder = (path) => fileURLToPath(new URL(`../${path}`, import.meta.url));
const SCHEMA = readFileSync(folder("migrations/0001_events.sql"), "utf8");
const CASES = JSON.parse(readFileSync(folder("test/event-cases.json"), "utf8"));
const SONGS = JSON.stringify({ tracks: Object.entries(CASES.songs).map(([id, duration]) => ({ id, duration })) });
const SITE = "https://oslohaggadone.github.io";
const USER = CASES.base.user_id;

// "now", "now-60d", "now+3d": a time relative to the test's
function when(value) {
  const relative = typeof value === "string" && value.match(/^now(?:([+-]\d+)([dhms]))?$/);
  if (!relative) return value;
  const unit = { d: 86_400_000, h: 3_600_000, m: 60_000, s: 1000 }[relative[2] ?? "s"];
  return new Date(Date.now() + Number(relative[1] ?? 0) * unit).toISOString();
}

function caseItem(c) {
  if ("item" in c) return c.item;
  const item = { ...CASES.base, ...(c.change ?? {}) };
  for (const name of c.remove ?? []) delete item[name];
  return { ...item, timestamp: when(item.timestamp) };
}

const event = (fields = {}) => ({ ...CASES.base, timestamp: when("now"), ...fields });

async function worker(t) {
  const server = createTestHarness({
    root: folder(""),
    workers: [{ configPath: "./wrangler.toml", vars: { SONGS, CATALOG_URL: "https://example.com/catalog.json" } }],
  });
  await server.listen();
  t.after(() => server.close());
  const db = (await server.getWorker().getEnv()).EVENTS;
  const statements = SCHEMA.replace(/--.*$/gm, "").split(";").map((s) => s.trim()).filter(Boolean);
  await db.batch(statements.map((sql) => db.prepare(sql)));
  const mf = { dispatchFetch: (url, init) => server.fetch(url, init) };
  const post = (body, headers = {}) => mf.dispatchFetch("https://api.test/events", {
    method: "POST", body: typeof body === "string" ? body : JSON.stringify(body),
    headers: { "Content-Type": "text/plain", ...headers },
  });
  const rows = async () => (await db.prepare("SELECT * FROM events ORDER BY event_id").all()).results;
  return { mf, post, rows };
}

test("the same events as app/server.py: stored or turned away", async (t) => {
  const { post, rows } = await worker(t);
  let before = 0;
  for (const c of CASES.cases) {
    const response = await post([caseItem(c)], { "CF-Connecting-IP": `198.51.100.${before % 250}` });
    assert.equal(response.status, 200, c.name);
    assert.equal((await response.json()).stored, c.stored ? 1 : 0, c.name);
    const now = await rows();
    if (c.expect) for (const [name, value] of Object.entries(c.expect)) assert.equal(now.at(-1)[name], value, c.name);
    before = now.length;
  }
});

test("events are stored as sent, in order", async (t) => {
  const { post, rows } = await worker(t);
  const batch = [event(), event({ event: "seek", from_s: 100, to_s: 40 }), event({ event: "ended", position_s: 120 })];
  const response = await post(batch, { Origin: SITE });
  assert.deepEqual(await response.json(), { stored: 3, rejected: 0 });
  assert.equal(response.headers.get("Access-Control-Allow-Origin"), SITE);
  const stored = await rows();
  assert.deepEqual(stored.map((row) => row.event), ["play", "seek", "ended"]);
  assert.equal(stored[1].from_s, 100);
  assert.equal(stored[1].position_s, null);
  assert.match(stored[0].client_ts, /Z$/);
  assert.match(stored[0].received_at, /^\d{4}-\d\d-\d\dT/);
  assert.deepEqual(Object.keys(stored[0]).sort(), ["client_ts", "event", "event_id", "from_s", "position_s", "received_at", "to_s", "track_id", "user_id"]);
});

test("other websites' pages can't send", async (t) => {
  const { post, rows } = await worker(t);
  assert.equal((await post(event(), { Origin: "https://example.com" })).status, 403);
  assert.equal((await post(event(), { Origin: "null" })).status, 403);
  const allowed = await post(event(), { Origin: SITE });
  assert.equal((await allowed.json()).stored, 1);
  assert.equal((await rows()).length, 1);
});

test("asking first from the site is answered; from elsewhere it isn't", async (t) => {
  const { mf } = await worker(t);
  const ask = (origin) => mf.dispatchFetch("https://api.test/events", {
    method: "OPTIONS", headers: { Origin: origin, "Access-Control-Request-Method": "POST" } });
  assert.equal((await ask(SITE)).headers.get("Access-Control-Allow-Origin"), SITE);
  assert.equal((await ask("https://example.com")).headers.get("Access-Control-Allow-Origin"), null);
});

test("a listener sending more than anyone listens is turned away, and no one else", async (t) => {
  const { post } = await worker(t);
  const minute = Array.from({ length: 120 }, () => event());
  assert.equal((await (await post(minute, { "CF-Connecting-IP": "203.0.113.1" })).json()).stored, 120);
  assert.equal((await post(event(), { "CF-Connecting-IP": "203.0.113.2" })).status, 429);
  const other = event({ user_id: "anon_" + "f".repeat(32) });
  assert.equal((await (await post(other, { "CF-Connecting-IP": "203.0.113.3" })).json()).stored, 1);
});

test("one connection sending too many requests is turned away", async (t) => {
  const { post } = await worker(t);
  const answers = [];
  for (let n = 0; n <= 60; n++) {
    const response = await post(event({ user_id: "anon_" + n.toString(16).padStart(32, "0") }), { "CF-Connecting-IP": "192.0.2.9" });
    answers.push(response.status);
  }
  assert.deepEqual(answers.slice(0, 60), Array(60).fill(200));
  assert.equal(answers[60], 429);
});

test("bad requests", async (t) => {
  const { post, rows } = await worker(t);
  assert.equal((await post("not json")).status, 400);
  assert.equal((await post("x".repeat(70_000))).status, 413);
  assert.equal((await post(Array.from({ length: 501 }, () => event()))).status, 413);
  assert.deepEqual(await rows(), []);
});

test("it says what it is, and has nothing else", async (t) => {
  const { mf } = await worker(t);
  assert.equal((await (await mf.dispatchFetch("https://api.test/")).json()).events, "POST /events");
  assert.equal((await mf.dispatchFetch("https://api.test/admin")).status, 404);
  assert.equal((await mf.dispatchFetch("https://api.test/events")).status, 405);
});
