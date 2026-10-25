// The listener's own marks on songs, kept in this browser only, like the settings (nothing is sent
// anywhere): favorites (the heart beside each song) and star ratings, 1 to 5, like iTunes had. The
// ratings show only while they're on in the settings, and are kept while they're off.

const FAVORITES_KEY = "synopsist.favorites";
const RATINGS_KEY = "synopsist.ratings";
const listeners = new Set();

function load(key) {
  try {
    return JSON.parse(localStorage.getItem(key));
  } catch {
    return null; // storage blocked, or something unreadable in it: start empty
  }
}

function save(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage blocked: the marks last until the page is closed
  }
}

const favorites = new Set([].concat(load(FAVORITES_KEY) ?? []).filter((id) => typeof id === "string"));
const ratings = Object.fromEntries(
  Object.entries(load(RATINGS_KEY) ?? {}).filter(([, stars]) => Number.isInteger(stars) && stars >= 1 && stars <= 5));

function changed(id, what) {
  for (const listener of listeners) listener(id, what);
}

export const isFavorite = (id) => favorites.has(id);

export function toggleFavorite(id) {
  if (!favorites.delete(id)) favorites.add(id);
  save(FAVORITES_KEY, [...favorites]);
  changed(id, "favorite");
}

export const ratingOf = (id) => ratings[id] ?? 0;

// 1 to 5 stars; the song's own rating again takes it away, as clicking it did in iTunes.
export function rate(id, stars) {
  if (stars === ratings[id]) delete ratings[id];
  else ratings[id] = stars;
  save(RATINGS_KEY, ratings);
  changed(id, "rating");
}

// fn(id, "favorite" | "rating"), whenever the listener marks a song
export function onMarksChange(fn) {
  listeners.add(fn);
}
