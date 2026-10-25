// The live EQ (Settings > Sound): see-through bars along the bottom of the screen, on every page and
// in full screen, rising and falling with the music as it's heard. eq.js's analyser hears the music
// after the EQ; each frame its spectrum is gathered into bars, the low notes on the left and the high
// on the right, spread by pitch, and drawn on one strip of canvas just above the player bar (which it
// follows down when the bar slides away in full screen; style.css). The bars are glass, like the
// buttons: a faint fill and a light along the top edge, in the theme's accent, or in full screen the
// album's color.
//
// It draws only while the music plays (and for the moment the bars take to settle after), 30 times a
// second (60 in full screen), and not at all with graphics Off. What's heard comes a little after
// what the analyser has (much later on Bluetooth headphones), so the bars show the spectrum from that
// long ago, as far as the browser knows the delay. They show it as at full volume: turning the music
// down doesn't shrink them.

import { graphics, liveEqSetting, onSettingsChange } from "./settings.js";

const LOW_HZ = 40; // the lowest and highest notes the bars show (the songs' MP3s have little higher)
const HIGH_HZ = 14000;
const BAR_PX = 30; // about one bar for every this many pixels across the screen,
const BAR_COUNT = [16, 64]; // but no fewer or more than these
const TILT_DB = 4; // music is quieter the higher it goes: each octave above 1 kHz is lifted this much
// (and each below lowered), so the bars stand about as tall from the bass to the treble
const QUIET_DB = -69; // a bar is empty when its notes are this quiet (after the tilt), and full when
const LOUD_DB = -40; // they're this loud: across the songs, about the quietest tenth and the loudest hundredth
const RISE = 0.6; // each frame a bar goes this much of the way up to the sound,
const FALL = 1.6; // and it falls this many times its full height a second when the sound does
const FILL = [0.24, 0.05]; // how see-through the bars are, at the top of the strip and at its bottom,
const EDGE = 0.7; // and the light along their top edges
const FRAME_MS = { full: 1000 / 60, page: 1000 / 30, low: 1000 / 30 }; // how often a new picture is drawn
const MAX_PIXEL_RATIO = { high: 2, low: 1 };
const COLOR_EVERY_MS = 500; // how often the color is checked (the theme, or the album in full screen)

// isFull() says whether the full-screen view is open
export function liveEq(canvas, player, eq, isFull) {
  const ctx = canvas.getContext("2d");
  let levels = new Float32Array(0); // each bar's height now, 0 to 1
  let spectrum = null; // the analyser's numbers, loudness by frequency
  let heard = []; // the last moment's bars, with when the analyser had them
  let color = "";
  let colorAt = -Infinity;
  let frame = 0;
  let last = 0;

  const on = () => liveEqSetting() && graphics() !== "off";

  function measure() {
    const ratio = Math.min(devicePixelRatio || 1, MAX_PIXEL_RATIO[graphics() === "low" ? "low" : "high"]);
    canvas.width = Math.round(canvas.clientWidth * ratio);
    canvas.height = Math.round(canvas.clientHeight * ratio);
    const count = Math.min(Math.max(Math.round(canvas.clientWidth / BAR_PX), BAR_COUNT[0]), BAR_COUNT[1]);
    if (levels.length !== count) levels = new Float32Array(count);
  }

  // The bars for what the analyser hears now: each the loudest part of its stretch of notes.
  function listen(analyser) {
    if (spectrum?.length !== analyser.frequencyBinCount) spectrum = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(spectrum);
    const perBin = analyser.context.sampleRate / analyser.fftSize; // Hz
    const range = analyser.maxDecibels - analyser.minDecibels;
    const volume = player.audio.muted ? 1 : Math.max(player.audio.volume, 0.01);
    const lift = -20 * Math.log10(volume); // as at full volume
    const bars = new Float32Array(levels.length);
    for (let i = 0; i < bars.length; i++) {
      const from = (LOW_HZ * (HIGH_HZ / LOW_HZ) ** (i / bars.length)) / perBin;
      const to = (LOW_HZ * (HIGH_HZ / LOW_HZ) ** ((i + 1) / bars.length)) / perBin;
      let loudest = 0;
      if (to - from < 1) {
        // narrower than the analyser can tell apart (the lowest notes): read between its numbers
        const at = (from + to) / 2;
        const k = Math.floor(at);
        loudest = spectrum[k] + (spectrum[k + 1] - spectrum[k]) * (at - k);
      } else {
        for (let k = Math.round(from); k < Math.round(to); k++) loudest = Math.max(loudest, spectrum[k]);
      }
      if (!loudest) continue;
      const db = analyser.minDecibels + (loudest / 255) * range + lift + TILT_DB * Math.log2((Math.sqrt(from * to) * perBin) / 1000);
      bars[i] = Math.min(Math.max((db - QUIET_DB) / (LOUD_DB - QUIET_DB), 0), 1);
    }
    return bars;
  }

  // What's heard now: what the analyser had that long ago.
  function heardNow(now, bars) {
    heard.push([now, bars]);
    const then = now - eq.latency() * 1000;
    while (heard.length > 1 && heard[1][0] <= then) heard.shift();
    return heard[0][1];
  }

  function draw() {
    const { width, height } = canvas;
    ctx.clearRect(0, 0, width, height);
    const count = levels.length;
    const gap = Math.max(1, Math.round(width / count / 6));
    const step = (width + gap) / count;
    const edge = Math.max(1, Math.round(height / 40));
    const glass = ctx.createLinearGradient(0, 0, 0, height);
    glass.addColorStop(0, `rgba(${color}, ${FILL[0]})`);
    glass.addColorStop(1, `rgba(${color}, ${FILL[1]})`);
    const light = `rgba(${color}, ${EDGE})`;
    for (let i = 0; i < count; i++) {
      const h = Math.round(levels[i] * height);
      if (h < 1) continue;
      const x = Math.round(i * step);
      const w = Math.round((i + 1) * step - gap) - x;
      ctx.fillStyle = glass;
      ctx.fillRect(x, height - h, w, h);
      ctx.fillStyle = light;
      ctx.fillRect(x, height - h, w, edge);
    }
  }

  function tick(now) {
    if (!on()) {
      stop();
      return;
    }
    // a new picture only as often as this view needs one
    const every = graphics() === "low" ? FRAME_MS.low : isFull() ? FRAME_MS.full : FRAME_MS.page;
    if (now - last < every - 4) {
      frame = requestAnimationFrame(tick);
      return;
    }
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    const analyser = player.playing ? eq.analyser() : null;
    const target = analyser ? heardNow(now, listen(analyser)) : null;
    if (!analyser) heard = [];
    let moving = false;
    for (let i = 0; i < levels.length; i++) {
      const to = target?.[i] ?? 0;
      levels[i] = to > levels[i] ? levels[i] + (to - levels[i]) * RISE : Math.max(to, levels[i] - FALL * dt);
      moving ||= levels[i] > 0;
    }
    if (now - colorAt > COLOR_EVERY_MS) {
      colorAt = now;
      color = getComputedStyle(canvas).color.match(/[\d.]+/g).slice(0, 3).join(", ");
    }
    draw();
    if (analyser || moving) frame = requestAnimationFrame(tick);
    else stop();
  }

  // nothing to draw: an empty canvas holds no memory
  function stop() {
    cancelAnimationFrame(frame);
    frame = 0;
    heard = [];
    levels.fill(0);
    canvas.width = 0;
    canvas.height = 0;
  }

  function wake() {
    canvas.hidden = !on();
    if (frame || !on() || !player.playing) return;
    measure();
    last = performance.now() - FRAME_MS.page;
    colorAt = -Infinity;
    frame = requestAnimationFrame(tick);
  }

  player.addEventListener("change", ({ detail }) => (detail === "state" || detail === "track") && wake());
  onSettingsChange((what) => (what === "liveEq" || what === "graphics") && wake());
  addEventListener("resize", () => frame && measure());
  wake();
}
