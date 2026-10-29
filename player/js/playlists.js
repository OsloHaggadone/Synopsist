// The listener's own playlists, kept in this browser like their favorites (js/marks.js) and never
// sent anywhere: each a name and its songs, in the order they were added (a song once per playlist).
// The music page lists them under "Playlists" in its sort dropdown; a song's "···" menu adds to them.

const KEY = "synopsist.playlists";
const listeners = new Set();

function load() {
  try {
    const stored = JSON.parse(localStorage.getItem(KEY));
    return Array.isArray(stored)
      ? stored.filter((p) => p && typeof p.id === "string" && typeof p.name === "string" && Array.isArray(p.tracks))
        .map((p) => ({ id: p.id, name: p.name, tracks: p.tracks.filter((id) => typeof id === "string") }))
      : [];
  } catch {
    return []; // storage blocked, or something unreadable in it: start empty
  }
}

const lists = load();

function save(what) {
  try {
    localStorage.setItem(KEY, JSON.stringify(lists));
  } catch {
    // storage blocked: the playlists last until the page is closed
  }
  for (const listener of listeners) listener(what);
}

export const playlists = () => lists;
export const playlist = (id) => lists.find((p) => p.id === id) ?? null;

export function createPlaylist(name, trackIds = []) {
  const id = `p${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  lists.push({ id, name, tracks: [...new Set(trackIds)] });
  save("created");
  return id;
}

export function renamePlaylist(id, name) {
  const p = playlist(id);
  if (!p) return;
  p.name = name;
  save("renamed");
}

export function deletePlaylist(id) {
  const at = lists.findIndex((p) => p.id === id);
  if (at < 0) return;
  lists.splice(at, 1);
  save("deleted");
}

// false when the song is in it already
export function addToPlaylist(id, trackId) {
  const p = playlist(id);
  if (!p || p.tracks.includes(trackId)) return false;
  p.tracks.push(trackId);
  save("added");
  return true;
}

export function removeFromPlaylist(id, trackId) {
  const p = playlist(id);
  if (!p) return;
  p.tracks = p.tracks.filter((t) => t !== trackId);
  save("removed");
}

// fn(what), whenever a playlist is made, renamed, deleted, or its songs change
export function onPlaylistsChange(fn) {
  listeners.add(fn);
}
