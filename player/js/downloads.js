// Downloads: songs kept in this browser to play without a connection, through the offline store
// (sw.js). The listener chooses them from a song's "···" menu, an album's, artist's, or playlist's
// download button, or Settings → Downloads; their listening meanwhile waits in the browser
// (js/listening.js) and is sent once there's a connection again. Downloading also keeps the site's
// own files, so the app opens offline. A song rebuilt since it was downloaded is downloaded again,
// in its new copy, the next time the site opens online.

const SITE = "synopsist-site"; // (sw.js's)
const SONGS = "synopsist-songs";
export const downloadsSupported = "serviceWorker" in navigator && "caches" in window && window.isSecureContext;
const saved = new Set(); // the downloaded songs' ids
const fetching = new Set(); // and the ones on their way
const listeners = new Set();
let songs = new Map();
let albums = new Map();

export const isDownloaded = (id) => saved.has(id);
export const isDownloading = (id) => fetching.has(id);
export const downloadedIds = () => [...saved];

// fn(), whenever a song is downloaded or removed
export function onDownloadsChange(fn) {
  listeners.add(fn);
}

function changed() {
  for (const fn of listeners) fn();
  navigator.serviceWorker?.ready.then((registration) => registration.active?.postMessage("downloads")).catch(() => {});
}

const here = () => new URL("./", document.baseURI).href;
const songId = (url) => decodeURIComponent(url.split("/").pop()).split(".")[0]; // audio/<id>.<version>.mp3

export async function setUpDownloads(trackList, albumList) {
  if (!downloadsSupported) return;
  songs = new Map(trackList.map((track) => [track.id, track]));
  albums = new Map(albumList.map((album) => [album.id, album]));
  navigator.serviceWorker.register(new URL("sw.js", document.baseURI), { scope: "./" }).catch(() => {});
  const cache = await caches.open(SONGS);
  const current = new Map(trackList.map((track) => [track.src, track.id]));
  const outdated = [];
  for (const request of await cache.keys()) {
    const id = current.get(request.url);
    if (id) saved.add(id);
    else outdated.push(request);
  }
  changed();
  if (navigator.onLine === false) return;
  for (const request of outdated) {
    const track = songs.get(songId(request.url));
    if (track) {
      try {
        await cache.add(track.src); // the new copy first: the old one stays until it's in
        saved.add(track.id);
      } catch {
        continue;
      }
    }
    await cache.delete(request); // (a song no longer on the site: gone)
  }
  if (outdated.length) changed();
  await prune();
  if (saved.size) keepTheSite();
}

// Covers and analysis of songs that have changed since (the site keeps only what it has now)
async function prune() {
  const cache = await caches.open(SITE);
  const wanted = new Set([...songs.values()].map((track) => track.analysis)
    .concat([...albums.values()].flatMap((album) => [album.cover, album.cover_large])).filter(Boolean));
  for (const request of await cache.keys()) {
    if (/\/library\/(covers|analysis)\//.test(request.url) && !wanted.has(request.url)) await cache.delete(request);
  }
}

// The site's own files, so it opens without a connection: everything this page has loaded, and the
// few it loads later
async function keepTheSite() {
  const cache = await caches.open(SITE);
  const root = here();
  const urls = new Set([root, ...["site.js", "song-effects.js", "song-notes.md", "manifest.webmanifest", "library/catalog.json"]
    .map((path) => new URL(path, root).href)]);
  for (const entry of performance.getEntriesByType("resource")) urls.add(entry.name.split("#")[0]);
  await Promise.all([...urls].filter((url) => url.startsWith(root) && !url.includes("/library/audio/") && !url.endsWith("/events"))
    .map(async (url) => (await cache.match(url, { ignoreSearch: true, ignoreVary: true })) || cache.add(url).catch(() => {})));
}

// The ones not downloaded yet, one after another; how many came in (the rest: no connection, or no room)
export async function download(ids) {
  const list = ids.map((id) => songs.get(id)).filter((track) => track && !saved.has(track.id) && !fetching.has(track.id));
  if (!list.length) return 0;
  navigator.storage?.persist?.().catch(() => {}); // (so the browser doesn't clear them to make room)
  for (const track of list) fetching.add(track.id);
  changed();
  const [songCache, siteCache] = await Promise.all([caches.open(SONGS), caches.open(SITE)]);
  keepTheSite();
  let done = 0;
  for (const track of list) {
    try {
      await songCache.add(track.src);
      const album = albums.get(track.album);
      await Promise.all([track.analysis, album?.cover, album?.cover_large].filter(Boolean)
        .map(async (url) => (await siteCache.match(url, { ignoreVary: true })) || siteCache.add(url)));
      saved.add(track.id);
      done++;
    } catch {
      // later: no connection, or no room
    }
    fetching.delete(track.id);
    changed(); // (each as it comes in)
  }
  return done;
}

export async function removeDownloads(ids) {
  const cache = await caches.open(SONGS);
  for (const id of ids) {
    const track = songs.get(id);
    if (track && saved.delete(id)) await cache.delete(track.src);
  }
  changed();
}

// What the site keeps in this browser, in bytes (the downloads mostly), or null if it can't tell
export async function storageUsed() {
  try {
    return (await navigator.storage.estimate()).usage ?? null;
  } catch {
    return null;
  }
}
