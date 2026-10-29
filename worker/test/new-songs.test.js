// A song published after the Worker last read the song list counts from its first plays: the Worker,
// run directly in Node with the song list, the database, and the clock faked (wrangler's harness
// can't fake the live site's catalog.json).

import assert from "node:assert/strict";
import { mock, test } from "node:test";
import worker from "../src/index.js";

const SITE = "https://oslohaggadone.com";
const CATALOG_URL = "https://site.test/Synopsist/library/catalog.json";
const USER = "anon_" + "ab".repeat(16);

test("a song published since the list was read counts at once, and made-up songs can't make it read more than once a minute", async () => {
  mock.timers.enable({ apis: ["Date"], now: Date.parse("2026-10-27T12:00:00Z") });
  let published = ["song-a"];
  const reads = [];
  mock.method(globalThis, "fetch", async (url) => {
    reads.push(String(url));
    return new Response(JSON.stringify({ tracks: published.map((id) => ({ id, duration: 200 })) }));
  });
  const stored = [];
  const env = {
    ORIGINS: SITE, CATALOG_URL,
    EVENTS: { prepare: () => ({ bind: (json) => ({ run: async () => stored.push(...JSON.parse(json)) }) }) },
  };
  let n = 0;
  const play = async (track) => {
    const event = { user_id: USER, track_id: track, event: "play", position_s: 1, timestamp: new Date(Date.now()).toISOString() };
    const request = new Request("https://api.test/events", {
      method: "POST", body: JSON.stringify([event]), headers: { Origin: SITE, "CF-Connecting-IP": `192.0.2.${n++}` } });
    return (await (await worker.fetch(request, env)).json()).stored;
  };

  assert.equal(await play("song-a"), 1);
  assert.deepEqual(reads, [CATALOG_URL]); // the first read

  published = ["song-a", "new-song"];
  assert.equal(await play("new-song"), 0); // read less than a minute ago: not again yet
  mock.timers.tick(61_000);
  assert.equal(await play("new-song"), 1); // read again at once, past the caches
  assert.match(reads.at(-1), /\?fresh=\d+$/);

  assert.equal(await play("not-a-song"), 0);
  assert.equal(reads.length, 2); // made-up songs don't make it read more than once a minute
  mock.timers.tick(61_000);
  assert.equal(await play("not-a-song"), 0);
  assert.equal(reads.length, 3);

  mock.timers.tick(10 * 60_000);
  assert.equal(await play("song-a"), 1);
  assert.equal(reads.at(-1), CATALOG_URL); // the regular read, every 10 minutes
  assert.deepEqual(stored.map((event) => event.track_id), ["song-a", "new-song", "song-a"]);
  mock.reset();
});
