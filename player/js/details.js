// The song details panel: a written summary of the song (its note in song-notes.md, or a
// description made from its audio analysis), then the measurements, led by how complex the song is,
// then the song moment by moment (its segments), where clicking a moment plays the song from there.
// The analysis is Essentia's, done offline: see src/synopsist/embed.py and describe.py.

import { clock, el } from "./dom.js";
import { t, tNodes } from "./i18n.js";

const MINUS = "−";

// A key as it's shown: "C# minor" -> "C♯ minor", "Bb major" -> "B♭ major" (or "B♭ 大调", in the
// listener's language); short, for the moments' column, "C♯ min"
export function keyName(key, short = false) {
  if (!key) return null;
  const note = key.split(" ")[0].replace("#", "♯").replace(/^([A-G])b/, "$1♭");
  if (key.endsWith(" major")) return short ? t("{note} maj", { note }) : t("{note} major", { note });
  if (key.endsWith(" minor")) return short ? t("{note} min", { note }) : t("{note} minor", { note });
  return note;
}
const number = (n, digits = 1) => `${n < 0 ? MINUS : ""}${Math.abs(n).toFixed(digits)}`;
const signed = (n, digits = 1) => `${n > 0 ? "+" : ""}${number(n, digits)}`;
const word = (value, steps) => steps.find(([below]) => value < below)?.[1] ?? steps.at(-1)[1];
const meter = (value) => el("span", { class: "meter", "aria-hidden": "true" }, el("i", { style: `width: ${value}%` }));

// --- complexity ------------------------------------------------------------------------------

function octaves(semitones) {
  return word(semitones, [[9, t("less than an octave")], [15, t("about an octave")], [21, t("about an octave and a half")],
    [27, t("about two octaves")], [Infinity, t("over two octaves")]]);
}

// What the analysis can hear (describe.py's names for the tags of Essentia's instrument classifier),
// in the listener's language
const INSTRUMENTS = {
  accordion: t("accordion"), "acoustic bass": t("acoustic bass"), "acoustic guitar": t("acoustic guitar"), bass: t("bass"),
  bell: t("bell"), bongo: t("bongo"), brass: t("brass"), cello: t("cello"), clarinet: t("clarinet"),
  "classical guitar": t("classical guitar"), "double bass": t("double bass"), "drum machine": t("drum machine"),
  drums: t("drums"), "electric guitar": t("electric guitar"), "electric piano": t("electric piano"), flute: t("flute"),
  guitar: t("guitar"), harmonica: t("harmonica"), harp: t("harp"), horn: t("horn"), keyboard: t("keyboard"), oboe: t("oboe"),
  orchestra: t("orchestra"), organ: t("organ"), pad: t("pad"), percussion: t("percussion"), piano: t("piano"),
  "pipe organ": t("pipe organ"), rhodes: t("rhodes"), saxophone: t("saxophone"), strings: t("strings"),
  synthesizer: t("synthesizer"), trombone: t("trombone"), trumpet: t("trumpet"), viola: t("viola"), violin: t("violin"),
  voice: t("voice"),
};

// The five parts of the rating: name, score, what it measures, and what this song's comes from.
function complexityParts(c) {
  const { parts } = c;
  const changes = c.chord_changes >= 1
    ? t("changing about every {n} seconds", { n: Math.max(1, Math.round(60 / c.chord_changes)) }) : t("hardly changing");
  const heard = c.instruments.slice(0, 4).map((name) => INSTRUMENTS[name] ?? name).join(t(", "));
  const more = c.instruments.length - 4;
  return [
    [t("Chords"), parts.chords, t("how many different chords, and how often they change"),
      c.chords_used ? t("about {n} chords, {changes}", { n: Math.max(1, Math.round(c.chords_used)), changes }) : t("no clear chords")],
    [t("Sound"), parts.sound, t("how dense and layered the sound is"),
      word(parts.sound, [[30, t("sparse and open")], [60, t("moderately full")], [Infinity, t("dense and layered")]])],
    [t("Dynamics"), parts.dynamics, t("how much the loudness rises and falls"),
      word(parts.dynamics, [[30, t("a steady level")], [60, t("some rise and fall")], [Infinity, t("big swings between quiet and loud")]])],
    [t("Instruments"), parts.instruments, t("how many different instruments the analysis hears"),
      heard ? (more > 0 ? t("{instruments}, and {n} more", { instruments: heard, n: more }) : heard) : t("no clear instruments")],
    [t("Melody"), parts.melody, t("how far the main melody ranges, and how varied its notes and steps are"),
      c.melody_range ? t("spans {range}", { range: octaves(c.melody_range) }) : t("no clear melody")],
  ];
}

function complexityRows(c) {
  const id = "complexity-info";
  const tag = el("button", {
    class: "info-tag",
    "aria-expanded": "false",
    "aria-controls": id,
    "aria-label": t("How complexity is rated"),
    title: t("How is this rated?"),
    onclick: (event) => {
      const box = document.getElementById(id);
      box.hidden = !box.hidden;
      event.currentTarget.setAttribute("aria-expanded", String(!box.hidden));
    },
  }, "i");
  return [
    el("dt", {}, t("Complexity"), tag),
    el("dd", { class: "complexity" }, meter(c.score), el("b", {}, String(c.score)),
      el("span", { class: "note" }, word(c.score, [[30, t("simple")], [50, t("moderate")], [70, t("rich")], [Infinity, t("intricate")]]))),
    el("dd", { class: "info-box", id, hidden: true },
      el("p", {}, t("The rating sums up five things the audio analysis measures in the song, each scored from 0 to 100 and averaged. It says how much is going on, not how good the song is.")),
      el("ul", { class: "parts" }, ...complexityParts(c).map(([name, value, what, here]) =>
        el("li", {},
          el("span", { class: "part-name" }, name),
          meter(value),
          el("span", { class: "part-value" }, String(value)),
          el("span", { class: "part-about" }, ...tNodes("{what}: {here}", { what, here: el("b", {}, here) })))))),
  ];
}

// --- the measurements and the moments ----------------------------------------------------------

function measurements(song, moments) {
  const window = moments.length ? moments[0].end - moments[0].start : 0;
  const { bass, mids, highs } = song.balance;
  return [
    [t("Length"), clock(song.duration)],
    [t("Tempo"), song.bpm ? `${Math.round(song.bpm)} BPM` : "—", song.bpm && word(song.bpm_confidence, [[1.5, t("loose beat")], [3.5, t("clear beat")], [Infinity, t("steady beat")]])],
    [t("Key"), keyName(song.key) ?? "—", song.key && word(song.key_strength, [[0.55, t("ambiguous")], [0.75, t("fairly clear")], [Infinity, t("clear")]])],
    [t("Loudness"), `${number(song.loudness_lufs)} LUFS`, t("plays here at {n}", { n: number(song.loudness_lufs + song.stream_gain_db) })],
    [t("Loudness range"), `${number(song.loudness_range)} LU`, word(song.loudness_range, [[4, t("even")], [8, t("moderate")], [Infinity, t("wide")]])],
    [t("Peak"), `${signed(song.peak_dbfs)} dBFS`],
    [t("Notes and hits"), t("{n} a second", { n: number(song.onset_rate) })],
    [t("Bass · mids · highs"), el("span", { class: "balance", role: "img", "aria-label": t("{bass}% bass, {mids}% mids, {highs}% highs", { bass, mids, highs }) },
      el("i", { style: `flex-grow: ${bass}` }), el("i", { style: `flex-grow: ${mids}` }), el("i", { style: `flex-grow: ${highs}` })),
      `${bass} · ${mids} · ${highs}%`],
    [t("Moments"), moments.length ? `${moments.length} × ${number(window, 0)} s` : "—"],
  ];
}

function momentRow(moment, onPlay) {
  const bands = t("bass {bass}, mids {mids}, highs {highs}", { bass: moment.bass, mids: moment.mids, highs: moment.highs });
  const loudness = moment.loudness == null ? t("silent") : t("{n} dB against the whole song", { n: signed(moment.loudness) });
  return el("li", { class: "moment", dataset: { start: moment.start, end: moment.end } },
    el("button", {
      class: "moment-main",
      onclick: () => onPlay(moment.start),
      title: t("Play from {time}. Loudness {loudness}; {bands}; {n} notes and hits a second",
        { time: clock(moment.start), loudness, bands, n: number(moment.onset_rate) }),
    },
      el("span", { class: "moment-time" }, clock(moment.start)),
      el("span", { class: "moment-level", "aria-hidden": "true" }, el("i", { style: `width: ${moment.level}%` })),
      el("span", { class: "moment-eq", "aria-hidden": "true" },
        el("i", { style: `--h: ${moment.bass / 100}` }), el("i", { style: `--h: ${moment.mids / 100}` }), el("i", { style: `--h: ${moment.highs / 100}` })),
      el("span", { class: "moment-bpm" }, moment.bpm ? String(Math.round(moment.bpm)) : "—"),
      el("span", { class: `moment-key${moment.key_strength < 0.5 ? " faint" : ""}` }, keyName(moment.key, true) ?? "—")));
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
    el("h3", {}, t("Summary")),
    ...(note?.length ? note : [data.description]).map((text) => el("p", { class: "details-summary" }, text)),
    el("h3", {}, t("Measurements")),
    el("dl", { class: "measures" },
      ...complexityRows(song.complexity),
      ...measurements(song, moments).flatMap(([name, value, aside]) => [
        el("dt", {}, name),
        el("dd", {}, value, aside ? el("span", { class: "note" }, aside) : null),
      ])),
    el("div", { class: "moments-head" },
      el("h3", {}, t("Moment by moment")),
      el("p", { class: "fine" }, t("Loudness, bass · mids · highs, tempo, and key. Click a moment to play from there."))),
    el("div", { class: "moment-columns", "aria-hidden": "true" },
      el("span", {}, t("Time")), el("span", {}, t("Loudness")), el("span", {}, t("B · M · H")), el("span", {}, "BPM"), el("span", {}, t("Key"))),
    el("ol", { class: "moments" }, ...moments.map((moment) => momentRow(moment, onPlay))));
}

// Highlight the moment playing now (time in seconds, or null for none).
export function markMoment(body, time) {
  for (const node of body.querySelectorAll(".moment")) {
    node.classList.toggle("current", time != null && time >= Number(node.dataset.start) && time < Number(node.dataset.end));
  }
}
