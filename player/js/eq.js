// The EQ (Settings > Sound): the music goes from the <audio> element through ten filters, one an
// octave from 32 Hz to 16 kHz, each raising or lowering its part of the sound by the preset's
// amount; then through the analyser the live EQ reads (js/liveeq.js), so the bars show what's heard;
// then a preamp that takes back the most the filters add anywhere, so a boost never clips (the rest
// gets a little quieter instead). A new preset glides in, so it doesn't click.
//
// This is the browser's Web Audio, which the backgrounds don't use (they read each song's analysis):
// it's set up only once the EQ or the live EQ is turned on, and from then on the music goes through
// it for the rest of the visit (a browser can't take it back out); Flat is every filter at 0, which
// sounds the same as none. Browsers let sound through Web Audio only after a click or a key press,
// so it's set up on the first one once it's wanted (a choice in the settings is one). On iPhones and
// iPads it may stop the music when the screen locks (the settings page says so there). If the songs
// ever come from another site (cloud storage), that site must allow it (CORS headers) and the
// <audio> element needs crossOrigin = "anonymous", or the music goes silent while it's on.

import { eqSetting, liveEqSetting, onSettingsChange } from "./settings.js";

const FREQUENCIES = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]; // each filter's middle, in Hz
const Q = 1.41; // each filter about an octave wide
// Each preset's gains, in dB, for the filters low to high (their names are in settings.js, and
// what they're called on the settings page in index.html).
const PRESETS = {
  flat: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
  "bass-boost": [6, 5, 4, 2, 0, 0, 0, 0, 0, 0],
  "bass-reduce": [-6, -5, -4, -2, 0, 0, 0, 0, 0, 0],
  "treble-boost": [0, 0, 0, 0, 0, 0, 1, 3, 5, 6],
  "vocal-boost": [-2, -2, -1, 0, 2, 3.5, 3.5, 2, 0, -1],
  electronic: [4.5, 4, 1.5, 0, -1.5, -1, 0, 1.5, 3, 4],
  "small-speakers": [-3, 0, 3.5, 3, 1, 0, 0, 1.5, 2, 1], // tiny speakers can't play the lowest notes anyway
};
const MARGIN_DB = 0.5; // the preamp takes back this much more than the biggest boost
const GLIDE_S = 0.03; // a new preset takes about three times this to settle in
// 200 frequencies from 20 Hz to 20 kHz, evenly spread by pitch, to find a preset's biggest boost on
const GRID = Float32Array.from({ length: 200 }, (_, i) => 20 * 1000 ** (i / 199));

export function equalize(player) {
  let graph = null; // the Web Audio nodes, once they're set up
  const wanted = () => eqSetting() !== "flat" || liveEqSetting();

  function setUp() {
    const context = new AudioContext({ latencyHint: "playback" });
    if (navigator.audioSession) navigator.audioSession.type = "playback"; // iPhone: play with the ringer off too
    const filters = () => FREQUENCIES.map((frequency) => new BiquadFilterNode(context, { type: "peaking", frequency, Q, gain: 0 }));
    graph = {
      context,
      filters: filters(),
      probes: filters(), // unconnected copies, to work out a preset's biggest boost
      analyser: new AnalyserNode(context, { fftSize: 4096, smoothingTimeConstant: 0.5, minDecibels: -85, maxDecibels: -25 }),
      preamp: new GainNode(context),
    };
    let node = new MediaElementAudioSourceNode(context, { mediaElement: player.audio });
    for (const next of [...graph.filters, graph.analyser, graph.preamp, context.destination]) node = node.connect(next);
    apply();
  }

  // The preset's gains, and the preamp down by its biggest boost.
  function apply() {
    const { context, filters, probes, preamp } = graph;
    const gains = PRESETS[eqSetting()] ?? PRESETS.flat;
    gains.forEach((gain, i) => {
      filters[i].gain.setTargetAtTime(gain, context.currentTime, GLIDE_S);
      probes[i].gain.value = gain;
    });
    const boost = biggestBoost(probes);
    preamp.gain.setTargetAtTime(boost > 0 ? 10 ** (-(boost + MARGIN_DB) / 20) : 1, context.currentTime, GLIDE_S);
  }

  // At a click or a key press: set up once it's wanted. And once the music goes through it, keep it
  // awake (a browser can put it to sleep), wanted or not, or the music would stop.
  function ready() {
    if (!graph) {
      if (!wanted() || (navigator.userActivation && !navigator.userActivation.hasBeenActive)) return; // (a touch counts on letting go)
      setUp();
    }
    if (graph.context.state !== "running") graph.context.resume().catch(() => {});
  }

  for (const name of ["pointerdown", "pointerup", "keydown"]) document.addEventListener(name, ready, true);
  player.audio.addEventListener("play", () => graph && ready());
  onSettingsChange((what) => {
    if (what !== "eq" && what !== "liveEq") return;
    ready();
    if (graph) apply();
  });

  return {
    // what the live EQ reads (none until the music goes through Web Audio)
    analyser: () => graph?.analyser ?? null,
    // how long after the analyser has a sound it's heard, in seconds (long on Bluetooth headphones)
    latency: () => (graph ? (graph.context.baseLatency || 0) + (graph.context.outputLatency || 0) : 0),
  };
}

// How many dB a set of filters raises the frequency they raise most (0 if they raise none).
function biggestBoost(filters) {
  const total = new Float32Array(GRID.length).fill(1);
  const magnitude = new Float32Array(GRID.length);
  const phase = new Float32Array(GRID.length);
  for (const filter of filters) {
    filter.getFrequencyResponse(GRID, magnitude, phase);
    for (let i = 0; i < GRID.length; i++) total[i] *= magnitude[i];
  }
  return Math.max(0, 20 * Math.log10(Math.max(...total)));
}
