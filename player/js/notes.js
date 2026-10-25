// Notes about each song (player/song-notes.md, written by hand), shown as the summary in its
// details panel. The file is plain text: each song starts with "## " and its track id, and
// everything until the next "## " is its note, in paragraphs separated by blank lines. Anything
// before the first song is ignored. A song without a note gets the automatic description from its
// analysis instead.

const NOTES_URL = new URL("song-notes.md", document.baseURI);
let notes = null; // a promise of track id -> paragraphs

export function parseNotes(text) {
  const found = new Map();
  let id = null;
  let lines = [];
  const finish = () => {
    const paragraphs = lines.join("\n").split(/\n\s*\n/).map((p) => p.replace(/\s+/g, " ").trim()).filter(Boolean);
    if (id && paragraphs.length) found.set(id, paragraphs);
  };
  for (const line of text.split(/\r?\n/)) {
    const heading = line.match(/^##\s+(\S+)/);
    if (heading) {
      finish();
      id = heading[1];
      lines = [];
    } else if (id) {
      lines.push(line);
    }
  }
  finish();
  return found;
}

export function loadNotes() {
  notes ??= fetch(NOTES_URL, { cache: "no-cache" })
    .then((response) => (response.ok ? response.text() : ""))
    .then(parseNotes)
    .catch(() => {
      notes = null; // try again next time
      return new Map();
    });
  return notes;
}
