// Synopsist's offline store (the public site's; js/downloads.js fills it): once the site has been
// opened it opens without a connection too, and the songs the listener downloads play offline.
//
// - The site's own files (the page, its code, fonts, images, the song list): from the network
//   first, so a push reaches everyone at once, and kept as last fetched for when there's none (or
//   it's too slow to wait for, TOO_SLOW_MS).
// - Covers and songs' analysis: kept once fetched (their names change whenever they do).
// - Songs: only the ones downloaded (SONGS, written by js/downloads.js), served from there in the
//   pieces the player asks for (byte ranges: iPhones ask for every song that way). Any other song is
//   left to the browser, streamed as it is without this.
// The listening events go to the API on another site, untouched here: when they can't be sent,
// js/listening.js keeps them until they can.
//
// The private copy has a store of its own (its sw.js, written over this one there).

const SITE = "synopsist-site";
const SONGS = "synopsist-songs";
const TOO_SLOW_MS = 4000;
// The site's files, found by their address alone: a server's "Vary" (Origin, say) would otherwise
// keep a stored copy from matching the module scripts and fonts, which ask with an Origin header,
// and the app wouldn't open offline
const ANY = { ignoreVary: true };
const scope = new URL(self.registration.scope);
let saved = null; // the downloaded songs' addresses, once read

async function readSaved() {
  const cache = await caches.open(SONGS);
  saved = new Set((await cache.keys()).map((request) => request.url));
}
readSaved();

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
// js/downloads.js, after a song is downloaded or removed
self.addEventListener("message", (event) => {
  if (event.data === "downloads") event.waitUntil(readSaved());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== scope.origin || !url.pathname.startsWith(scope.pathname)) return;
  const path = url.pathname.slice(scope.pathname.length);
  if (path.startsWith("library/audio/")) {
    if (saved && !saved.has(url.origin + url.pathname)) return; // not downloaded: the browser streams it
    event.respondWith(song(request));
  } else if (path.startsWith("library/covers/") || path.startsWith("library/analysis/")) {
    event.respondWith(kept(request));
  } else {
    event.respondWith(fresh(event, request));
  }
});

// A downloaded song, whole or the piece asked for
async function song(request) {
  const url = new URL(request.url);
  const response = await caches.match(url.origin + url.pathname, { cacheName: SONGS, ...ANY });
  if (!response) return fetch(request);
  const blob = await response.blob();
  const size = blob.size;
  const type = response.headers.get("Content-Type") || "audio/mpeg";
  const range = /^bytes=(\d*)-(\d*)$/.exec(request.headers.get("Range") || "");
  if (!range || (range[1] === "" && range[2] === "")) {
    return new Response(blob, { headers: { "Content-Type": type, "Content-Length": String(size), "Accept-Ranges": "bytes" } });
  }
  // "bytes=100-", "bytes=100-199", or the last n bytes, "bytes=-500"
  const start = range[1] === "" ? Math.max(size - Number(range[2]), 0) : Number(range[1]);
  const end = range[1] !== "" && range[2] !== "" ? Math.min(Number(range[2]), size - 1) : size - 1;
  if (start > end) return new Response(null, { status: 416, headers: { "Content-Range": `bytes */${size}` } });
  return new Response(blob.slice(start, end + 1), {
    status: 206,
    headers: { "Content-Type": type, "Content-Length": String(end - start + 1), "Content-Range": `bytes ${start}-${end}/${size}`, "Accept-Ranges": "bytes" },
  });
}

// A cover or a song's analysis: kept once fetched
async function kept(request) {
  const cache = await caches.open(SITE);
  const hit = await cache.match(request, ANY);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok) cache.put(request, response.clone());
  return response;
}

// The site's own files: the network's, kept for next time; without it (or too slow), the last kept
async function fresh(event, request) {
  const cache = await caches.open(SITE);
  const fetched = fetch(request).then((response) => {
    if (response.ok && response.type === "basic") {
      const copy = response.clone();
      event.waitUntil(cache.put(request, copy));
    }
    return response;
  });
  const fallback = async () => (await cache.match(request, { ignoreSearch: true, ...ANY }))
    ?? (request.mode === "navigate" ? cache.match(scope.href, ANY) : undefined);
  const slow = new Promise((resolve) => setTimeout(() => resolve("slow"), TOO_SLOW_MS));
  try {
    const first = await Promise.race([fetched, slow]);
    if (first !== "slow") return first;
    return (await fallback()) ?? (await fetched);
  } catch (error) {
    const hit = await fallback();
    if (hit) return hit;
    throw error;
  }
}
