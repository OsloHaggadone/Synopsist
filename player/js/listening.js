// Raw listening events, in the format the backend expects (see "Event format" in CLAUDE.md).
// The player only reports what happened; the backend decides what counts as a replay.
//
// Phase 2: events are kept in memory, and printed to the browser console when the page URL has
// ?debug. Phase 3 sends them to the backend with an anonymous ID stored in this browser, and must
// delete that ID when the listener turns sharing off (the privacy note promises this).

const SHARE_KEY = "synopsist.shareListening";
const DEBUG = new URLSearchParams(location.search).has("debug");
const recorded = [];
if (DEBUG) window.synopsistEvents = recorded;

function storedChoice() {
  try {
    return localStorage.getItem(SHARE_KEY);
  } catch {
    return null; // storage blocked: fall back to the default
  }
}

// On unless the listener turned it off, or their browser sends Global Privacy Control.
export function sharingEnabled() {
  const choice = storedChoice();
  return choice === null ? !navigator.globalPrivacyControl : choice === "1";
}

export function setSharing(on) {
  try {
    localStorage.setItem(SHARE_KEY, on ? "1" : "0");
  } catch {
    // the choice lasts until the page is closed
  }
}

const round = (seconds) => Math.round(seconds * 10) / 10;

// event: play | pause | seek | skip | ended | position
// fields: { position_s } for every event except seek, which has { from_s, to_s }
export function logEvent(trackId, event, fields) {
  if (!sharingEnabled()) return;
  const record = { track_id: trackId, event, timestamp: new Date().toISOString() };
  for (const [name, value] of Object.entries(fields)) record[name] = round(value);
  recorded.push(record);
  if (DEBUG) console.log("[listening]", JSON.stringify(record));
}
