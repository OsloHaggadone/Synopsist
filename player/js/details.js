// The song details panel: a written summary of the song (its note in song-notes.md, or a
// description made from its audio analysis), then the measurements, led by how complex the song is,
// then the song moment by moment (its segments), where clicking a moment plays the song from there.
// The analysis is Essentia's, done offline: see src/synopsist/embed.py and describe.py.

import { clock, el } from "./dom.js";

const MINUS = "−";

// "C#" -> "C♯", "Bb" -> "B♭"
const prettyKey = (key) => key?.replace("#", "♯").replace(/^([A-G])b/, "$1♭");
const shortKey = (key) => prettyKey(key)?.replace(" major", " maj").replace(" minor", " min");
const number = (n, digits = 1) => `${n < 0 ? MINUS : ""}${Math.abs(n).toFixed(digits)}`;
const signed = (n, digits = 1) => `${n > 0 ? "+" : ""}${number(n, digits)}`;
const word = (value, steps) => steps.find(([below]) => value < below)?.[1] ?? steps.at(-1)[1];
const meter = (value) => el("span", { class: "meter", "aria-hidden": "true" }, el("i", { style: `width: ${value}%` }));

// --- complexity ------------------------------------------------------------------------------

function octaves(semitones) {
  return word(semitones, [[9, "less than an octave"], [15, "about an octave"], [21, "about an octave and a half"],
    [27, "about two octaves"], [Infinity, "over two octaves"]]);
}

// The five parts of the rating: name, score, what it measures, and what this song's comes from.
function complexityParts(c) {
  const { parts } = c;
  const changes = c.chord_changes >= 1 ? `changing about every ${Math.max(1, Math.round(60 / c.chord_changes))} seconds` : "hardly changing";
  const heard = c.instruments.slice(0, 4).join(", ");
  return [
    ["Chords", parts.chords, "how many different chords, and how often they change",
      c.chords_used ? `about ${Math.max(1, Math.round(c.chords_used))} chords, ${changes}` : "no clear chords"],
    ["Sound", parts.sound, "how dense and layered the sound is",
      word(parts.sound, [[30, "sparse and open"], [60, "moderately full"], [Infinity, "dense and layered"]])],
    ["Dynamics", parts.dynamics, "how much the loudness rises and falls",
      word(parts.dynamics, [[30, "a steady level"], [60, "some rise and fall"], [Infinity, "big swings between quiet and loud"]])],
    ["Instruments", parts.instruments, "how many different instruments the analysis hears",
      heard ? `${heard}${c.instruments.length > 4 ? `, and ${c.instruments.length - 4} more` : ""}` : "no clear instruments"],
    ["Melody", parts.melody, "how far the main melody ranges, and how varied its notes and steps are",
      c.melody_range ? `spans ${octaves(c.melody_range)}` : "no clear melody"],
  ];
}

function complexityRows(c) {
  const id = "complexity-info";
  const tag = el("button", {
    class: "info-tag",
    "aria-expanded": "false",
    "aria-controls": id,
    "aria-label": "How complexity is rated",
    title: "How is this rated?",
    onclick: (event) => {
      const box = document.getElementById(id);
      box.hidden = !box.hidden;
      event.currentTarget.setAttribute("aria-expanded", String(!box.hidden));
    },
  }, "i");
  return [
    el("dt", {}, "Complexity", tag),
    el("dd", { class: "complexity" }, meter(c.score), el("b", {}, String(c.score)),
      el("span", { class: "note" }, word(c.score, [[30, "simple"], [50, "moderate"], [70, "rich"], [Infinity, "intricate"]]))),
    el("dd", { class: "info-box", id, hidden: true },
      el("p", {}, "The rating sums up five things the audio analysis measures in the song, each scored from 0 to " +
        "100 and averaged. It says how much is going on, not how good the song is."),
      el("ul", { class: "parts" }, ...complexityParts(c).map(([name, value, what, here]) =>
        el("li", {},
          el("span", { class: "part-name" }, name),
          meter(value),
          el("span", { class: "part-value" }, String(value)),
          el("span", { class: "part-about" }, `${what}: `, el("b", {}, here)))))),
  ];
}

// --- the measurements and the moments ----------------------------------------------------------

function measurements(song, moments) {
  const window = moments.length ? moments[0].end - moments[0].start : 0;
  const { bass, mids, highs } = song.balance;
  return [
    ["Length", clock(song.duration)],
    ["Tempo", song.bpm ? `${Math.round(song.bpm)} BPM` : "—", song.bpm && word(song.bpm_confidence, [[1.5, "loose beat"], [3.5, "clear beat"], [Infinity, "steady beat"]])],
    ["Key", prettyKey(song.key) ?? "—", song.key && word(song.key_strength, [[0.55, "ambiguous"], [0.75, "fairly clear"], [Infinity, "clear"]])],
    ["Loudness", `${number(song.loudness_lufs)} LUFS`, `plays here at ${number(song.loudness_lufs + song.stream_gain_db)}`],
    ["Loudness range", `${number(song.loudness_range)} LU`, word(song.loudness_range, [[4, "even"], [8, "moderate"], [Infinity, "wide"]])],
    ["Peak", `${signed(song.peak_dbfs)} dBFS`],
    ["Notes and hits", `${number(song.onset_rate)} a second`],
    ["Bass · mids · highs", el("span", { class: "balance", role: "img", "aria-label": `${bass}% bass, ${mids}% mids, ${highs}% highs` },
      el("i", { style: `flex-grow: ${bass}` }), el("i", { style: `flex-grow: ${mids}` }), el("i", { style: `flex-grow: ${highs}` })),
      `${bass} · ${mids} · ${highs}%`],
    ["Moments", moments.length ? `${moments.length} × ${number(window, 0)} s` : "—"],
  ];
}

function momentRow(moment, onPlay) {
  const bands = `bass ${moment.bass}, mids ${moment.mids}, highs ${moment.highs}`;
  const loudness = moment.loudness == null ? "silent" : `${signed(moment.loudness)} dB against the whole song`;
  return el("li", { class: "moment", dataset: { start: moment.start, end: moment.end } },
    el("button", {
      class: "moment-main",
      onclick: () => onPlay(moment.start),
      title: `Play from ${clock(moment.start)}. Loudness ${loudness}; ${bands}; ${number(moment.onset_rate)} notes and hits a second`,
    },
      el("span", { class: "moment-time" }, clock(moment.start)),
      el("span", { class: "moment-level", "aria-hidden": "true" }, el("i", { style: `width: ${moment.level}%` })),
      el("span", { class: "moment-eq", "aria-hidden": "true" },
        el("i", { style: `--h: ${moment.bass / 100}` }), el("i", { style: `--h: ${moment.mids / 100}` }), el("i", { style: `--h: ${moment.highs / 100}` })),
      el("span", { class: "moment-bpm" }, moment.bpm ? String(Math.round(moment.bpm)) : "—"),
      el("span", { class: `moment-key${moment.key_strength < 0.5 ? " faint" : ""}` }, shortKey(moment.key) ?? "—")));
}

// Fill the panel for one song: its analysis (data) and note (paragraphs, or null for the automatic
// description), or a message while there's no analysis. `cover` is its album art; onPlay(seconds)
// plays it from a moment.
export function renderDetails(body, { track, album, data, note, message, cover, onPlay }) {
  const head = el("div", { class: "details-song" },
    el("div", { class: "details-cover", "aria-hidden": "true" }, cover),
    el("div", {}, el("p", { class: "details-title" }, track.title), el("p", { class: "details-album" }, album.title)));
  if (!data) {
    body.replaceChildren(head, el("p", { class: "status" }, message));
    return;
  }
  const { song, moments } = data;
  body.replaceChildren(
    head,
    el("h3", {}, "Summary"),
    ...(note?.length ? note : [data.description]).map((text) => el("p", { class: "details-summary" }, text)),
    el("h3", {}, "Measurements"),
    el("dl", { class: "measures" },
      ...complexityRows(song.complexity),
      ...measurements(song, moments).flatMap(([name, value, aside]) => [
        el("dt", {}, name),
        el("dd", {}, value, aside ? el("span", { class: "note" }, aside) : null),
      ])),
    el("div", { class: "moments-head" },
      el("h3", {}, "Moment by moment"),
      el("p", { class: "fine" }, "Loudness, bass · mids · highs, tempo, and key. Click a moment to play from there.")),
    el("div", { class: "moment-columns", "aria-hidden": "true" },
      el("span", {}, "Time"), el("span", {}, "Loudness"), el("span", {}, "B · M · H"), el("span", {}, "BPM"), el("span", {}, "Key")),
    el("ol", { class: "moments" }, ...moments.map((moment) => momentRow(moment, onPlay))));
}

// Highlight the moment playing now (time in seconds, or null for none).
export function markMoment(body, time) {
  for (const node of body.querySelectorAll(".moment")) {
    node.classList.toggle("current", time != null && time >= Number(node.dataset.start) && time < Number(node.dataset.end));
  }
}
