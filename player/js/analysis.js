// Each song's published analysis (library/analysis/, written by src/synopsist/publish.py): its bass,
// mids, and highs curves, the outline of its loudness, and its measurements, whole and moment by
// moment. Fetched once, the first time anything needs it, and shared by the backgrounds (vibe.js),
// the seek bar's wave, and the song details panel.

const loaded = new Map(); // track id -> a promise of its analysis

export function loadAnalysis(track) {
  if (!track?.analysis) return Promise.resolve(null);
  if (!loaded.has(track.id)) {
    const request = fetch(track.analysis)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .catch(() => {
        loaded.delete(track.id); // try again next time
        return null;
      });
    loaded.set(track.id, request);
  }
  return loaded.get(track.id);
}
