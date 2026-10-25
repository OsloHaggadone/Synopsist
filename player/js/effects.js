// Song effects: for the songs in song-effects.js, glowing particles and rays of light while the song
// plays, each song with its own look, and in full screen its own background light (its "scene", in
// place of the album's moving glows). The chorus changes the look (more particles, faster and
// brighter, rays, a brighter scene, a lighter vignette, and a swell of light with new particles
// drifting in), and the change builds up into the drop in the music's own time: it starts a few
// measures before, on a measure line (fewer measures in a slow song, more in a fast one), slowly,
// and is complete the moment the chorus lands. On the drop itself the light gives a small pop that
// rings out over a few seconds; the chorus look eases back over a few measures after the chorus.
// When the chorus plays comes with the song's analysis (src/synopsist/structure.py), and its tempo
// with the catalog, unless song-effects.js gives them itself.
//
// Behind the page everything goes on one canvas. In full screen it's layered for depth: the scene,
// then most particles behind the cover, then the rays and the nearest particles (bigger, softer,
// faster) in front of it, under the vignette. It's only drawn while one of these songs plays: in
// full screen 60 times a second, behind the page (where it's subtler) 30. With Low graphics there
// are half as many particles, all behind the cover, drawn 30 times a second at a lower resolution;
// with graphics Off (and for listeners who ask for less motion) there's nothing at all. Like the
// backgrounds (vibe.js), it follows the playback position, never the audio itself.

import { BRIGHTNESS, SONG_EFFECTS } from "../song-effects.js";
import { loadAnalysis } from "./analysis.js";
import { graphics, onSettingsChange } from "./settings.js";

const DENSITY = { high: 1, low: 0.5 }; // every particle count is multiplied by this, by graphics setting
const FULL_HD = 1920 * 1080; // the counts and sizes in song-effects.js are for a screen this size
const MAX_PIXEL_RATIO = { high: 1.25, low: 1 }; // soft shapes don't need sharper, and fewer pixels are cheaper
const FRAME_MS = { full: 1000 / 60, page: 1000 / 30, low: 1000 / 30 }; // how often a new picture is drawn
const FADE_S = 1.2; // the effects fade in when the song plays, and out when it stops
const SWAP_S = 0.6; // a song with another look: the old look fades out this fast first
// How the chorus comes and goes is counted in the song's beats and measures (4 beats, unless
// song-effects.js says otherwise): of each of these, the whole number (COUNTS) that comes closest to
// the seconds given here at the song's tempo. So a slow song builds up over fewer measures and a fast
// one over more, each taking a few seconds, and a build-up starts on a measure line (the drop lands
// on one). The same length comes out whether the tempo was heard as 80 or as 160.
const COUNTS = [1, 2, 4, 8];
const BUILD = [4, "measure"]; // the chorus look builds up over about this long before the drop, slowly, then faster,
const FALL = [5, "measure"]; // and eases back over about this long after the chorus
const SWELL_IN = [1.5, "beat"]; // the swell of light builds up over about this long before the drop,
const SWELL_S = 3; // and settles over about this long after it
const POP = 0.35; // on the drop the light rises this much more (the swell itself peaks at 1),
const POP_IN_S = 0.15; // this quickly,
const POP_S = 1.2; // and rings out slowly, like a reverb: down by about two thirds every this long
const GLIDE_S = 0.5; // in full screen the cover and its scene glide this long when the player bar comes or
// goes (style.css: .visual-frame and .scene, translate 0.5s var(--ease-out)); the rays glide with them
const DARK = 0.85; // a break before a drop (song-effects.js, breakBeats) takes this much of the light away,
const DARK_IN_S = 0.12; // this quickly, then brings it back up into the drop
const CATCH_S = 1.25; // after a jump in the song the look takes at least this long to catch up
const KICK_S = 1.4; // a burst's push fades over about this long
const FADE_IN_S = 2; // each new particle fades in over this long,
const BURST_IN = [1.2, "beat"]; // and a burst's start about this long before the drop, fully there on it
const FRONT = 0.15; // the share of particles in front of the cover, unless song-effects.js says otherwise
const FRONT_SIZE = 2.4; // those are nearer: bigger,
const FRONT_SPEED = 1.6; // faster,
const FRONT_ALPHA = 0.55; // and out of focus, so softer and fainter
const VIGNETTE = 0.7; // the vignette's usual strength (style.css, .visual-vignette)
const PAGE_STRENGTH = 0.8; // behind the page the effects are a little fainter than in full screen
const LIGHT_STRENGTH = 0.7; // and fainter again on the light page, where they're drawn in deeper colors
const TAU = Math.PI * 2;
const DEBUG = new URLSearchParams(location.search).has("debug"); // ?debug: print the chorus times to the console

const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
const ease = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x));

// CSS's cubic-bezier(x1, y1, x2, y2), as a function from 0 to 1
function bezier(x1, y1, x2, y2) {
  const along = (t, a, b) => 3 * a * t * (1 - t) ** 2 + 3 * b * t * t * (1 - t) + t ** 3;
  return (x) => {
    let lo = 0;
    let hi = 1;
    for (let i = 0; i < 24; i++) {
      const mid = (lo + hi) / 2;
      if (along(mid, x1, x2) < x) lo = mid;
      else hi = mid;
    }
    return along((lo + hi) / 2, y1, y2);
  };
}
const easeOut = bezier(0.2, 0.9, 0.25, 1); // style.css's --ease-out
const between = ([lo, hi]) => lo + Math.random() * (hi - lo);
const quality = () => (graphics() === "low" ? "low" : "high"); // (with Off nothing is drawn)

// 70.5 -> "1:10.5"
const clockTime = (seconds) => `${Math.floor(seconds / 60)}:${(seconds % 60).toFixed(1).padStart(4, "0")}`;

// A length in a song's own time, from [seconds, "beat" or "measure"] and its tempo ({bpm,
// beatsPerBar}): the whole number of beats or measures (COUNTS) that comes closest to those seconds.
// Returns [seconds, how many]; without a tempo, just the seconds.
function inTime([seconds, unit], tempo) {
  if (!tempo.bpm) return [seconds, 0];
  const one = (60 / tempo.bpm) * (unit === "measure" ? tempo.beatsPerBar : 1);
  const off = (count) => Math.abs(Math.log((count * one) / seconds)); // how far off, as a ratio
  const count = COUNTS.reduce((best, n) => (off(n) < off(best) ? n : best));
  return [count * one, count];
}

// How long a song's chorus takes to come and go, in seconds, from its tempo (its own in
// song-effects.js, else the catalog's, which comes from its analysis): {build, fall, swellIn,
// burstIn}, and how that counts in beats and measures, for ?debug.
const HOW = { build: "builds up over", fall: "eases back over", swellIn: "swells over", burstIn: "a burst fades in over" };
function chorusTiming(own, track) {
  const tempo = { bpm: own?.bpm ?? track?.bpm ?? 0, beatsPerBar: own?.beatsPerBar ?? 4 };
  const timing = { beat: tempo.bpm ? 60 / tempo.bpm : 0.5, about: [] };
  for (const [name, length] of Object.entries({ build: BUILD, fall: FALL, swellIn: SWELL_IN, burstIn: BURST_IN })) {
    // a song can say how many measures its build-up takes
    const fixed = name === "build" && own?.buildMeasures && tempo.bpm;
    const [seconds, count] = fixed ? [own.buildMeasures * tempo.beatsPerBar * timing.beat, own.buildMeasures] : inTime(length, tempo);
    timing[name] = seconds;
    timing.about.push(`${HOW[name]} ${count ? `${count} ${length[1]}${count === 1 ? "" : "s"}, ` : ""}${seconds.toFixed(1)} s`);
  }
  timing.about = `${tempo.bpm ? `at ${tempo.bpm} BPM` : "with no tempo"} it ${timing.about.join("; ")}`;
  return timing;
}

// A chorus from song-effects.js: "1:10-1:50", or {at: "1:10-1:50", size, breakBeats}
// -> [start, end, size, breakBeats] in seconds (size 1 and no break unless it says)
function span(entry) {
  const { at, size = 1, breakBeats = 0 } = typeof entry === "string" ? { at: entry } : entry;
  const seconds = (clock) => clock.split(":").reduce((total, part) => total * 60 + Number(part), 0);
  const [start, end] = String(at).split("-").map((part) => seconds(part.trim()));
  return start < end ? [start, end, size, breakBeats] : null;
}

// --- the shapes: drawn once for each color, then stamped -----------------------------------------

const sprites = new Map(); // "shape color light|dark soft|sharp" -> canvas
const EXTENT = { dot: 3, spark: 4, shard: 2.4, petal: 2.2 }; // drawn size, glow included, in radii
const SOFT_PAD = 0.5; // an out-of-focus shape gets this much room on each side for its blur (of its size)

function rgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

const rgba = ([r, g, b], alpha) => `rgba(${r}, ${g}, ${b}, ${alpha})`;

// On the light page a glowing color would vanish into the background: the same hue, darker and richer.
function deepen(color) {
  const [r, g, b] = color.map((c) => c / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const range = max - min;
  let hue = 0;
  if (range) hue = max === r ? (g - b) / range : max === g ? (b - r) / range + 2 : (r - g) / range + 4;
  hue = (hue + 6) % 6;
  const lightness = Math.min((max + min) / 2, 0.42);
  const saturation = Math.max(range ? range / (1 - Math.abs(max + min - 1)) : 0, 0.5);
  const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
  const x = chroma * (1 - Math.abs((hue % 2) - 1));
  const parts = [[chroma, x, 0], [x, chroma, 0], [0, chroma, x], [0, x, chroma], [x, 0, chroma], [chroma, 0, x]][Math.floor(hue)];
  return parts.map((v) => Math.round((v + lightness - chroma / 2) * 255));
}

function sprite(shape, color, light, soft = false) {
  const key = `${shape} ${color} ${light ? "light" : "dark"} ${soft ? "soft" : "sharp"}`;
  if (sprites.has(key)) return sprites.get(key);
  const canvas = document.createElement("canvas");
  if (soft) {
    // out of focus: the same shape, blurred (where the browser can blur on a canvas)
    const sharp = sprite(shape, color, light);
    const pad = sharp.width * SOFT_PAD;
    canvas.width = sharp.width + 2 * pad;
    canvas.height = sharp.height + 2 * pad;
    const ctx = canvas.getContext("2d");
    ctx.filter = `blur(${sharp.width / 16}px)`;
    ctx.drawImage(sharp, pad, pad);
    sprites.set(key, canvas);
    return canvas;
  }
  const tint = light ? deepen(rgb(color)) : rgb(color);
  const size = 64;
  canvas.width = size;
  canvas.height = shape === "beam" ? 512 : size;
  const ctx = canvas.getContext("2d");
  const mid = size / 2;
  const radial = (stops) => {
    const gradient = ctx.createRadialGradient(mid, mid, 0, mid, mid, mid);
    for (const [at, c, alpha] of stops) gradient.addColorStop(at, rgba(c, alpha));
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, size, size);
  };
  const white = light ? tint : [255, 255, 255];
  if (shape === "beam") {
    // a ray of light pointing down: brightest down its middle and where it starts, gone by its end
    const across = ctx.createLinearGradient(0, 0, size, 0);
    for (const [at, alpha] of [[0, 0], [0.22, 0.12], [0.5, 1], [0.78, 0.12], [1, 0]]) across.addColorStop(at, rgba(tint, alpha));
    ctx.fillStyle = across;
    ctx.fillRect(0, 0, size, canvas.height);
    ctx.globalCompositeOperation = "destination-in";
    const along = ctx.createLinearGradient(0, 0, 0, canvas.height);
    for (const [at, alpha] of [[0, 1], [0.35, 0.5], [1, 0]]) along.addColorStop(at, `rgba(0, 0, 0, ${alpha})`);
    ctx.fillStyle = along;
    ctx.fillRect(0, 0, size, canvas.height);
  } else if (shape === "spark") {
    radial([[0, white, 1], [0.08, tint, 0.95], [0.22, tint, 0.35], [1, tint, 0]]);
  } else if (shape === "shard") {
    // a sliver of glass: a tall diamond, lit along one side
    ctx.shadowColor = rgba(tint, 0.9);
    ctx.shadowBlur = 8;
    const fill = ctx.createLinearGradient(mid - 10, mid - 16, mid + 10, mid + 16);
    fill.addColorStop(0, rgba(white, 0.95));
    fill.addColorStop(0.45, rgba(tint, 0.8));
    fill.addColorStop(1, rgba(tint, 0.25));
    ctx.fillStyle = fill;
    ctx.beginPath();
    ctx.moveTo(mid, mid - 18);
    ctx.lineTo(mid + 10, mid);
    ctx.lineTo(mid, mid + 18);
    ctx.lineTo(mid - 10, mid);
    ctx.closePath();
    ctx.fill();
  } else if (shape === "petal") {
    // a soft oval: a round glow squashed flat
    ctx.setTransform(1, 0, 0, 0.55, 0, mid * 0.45);
    radial([[0, tint, 0.95], [0.5, tint, 0.65], [1, tint, 0]]);
  } else {
    radial([[0, tint, 1], [0.18, tint, 0.8], [0.45, tint, 0.25], [1, tint, 0]]);
  }
  sprites.set(key, canvas);
  return canvas;
}

// Every look's shapes, drawn ahead of time in idle moments after the page loads, so that a song's
// effects never stop to draw them (the moment a new look starts is when it would show).
function prewarm() {
  const jobs = [];
  for (const look of new Set(Object.values(SONG_EFFECTS).filter((entry) => typeof entry === "object"))) {
    const shape = look.particles.shape ?? "dot";
    for (const color of new Set([...look.particles.colors, ...(look.chorus?.colors ?? [])])) {
      jobs.push(() => sprite(shape, color, false), () => sprite(shape, color, false, true));
    }
    if (look.rays) jobs.push(() => sprite("beam", look.rays.color, false));
  }
  const idle = (fn) => (window.requestIdleCallback ? requestIdleCallback(fn, { timeout: 5000 }) : setTimeout(() => fn({ timeRemaining: () => 8 }), 500));
  const work = (deadline) => {
    while (jobs.length && deadline.timeRemaining() > 2) jobs.shift()();
    if (jobs.length) idle(work);
  };
  idle(work);
}

// --- a song's own background light in full screen --------------------------------------------------

// One light of a scene (song-effects.js): a glow (an oval of light) or a band (a soft stripe across
// the screen). Each is a tiny picture of its light, drawn once and stretched to size by the graphics
// card: soft light looks the same either way, but a light the size of the screen would otherwise be
// painted pixel by pixel whenever it comes back. How bright it is follows the chorus, the landing,
// and the bass, in style.css.
function sceneLight(light) {
  const band = light.light === "band";
  const node = document.createElement("canvas");
  node.className = "light";
  node.width = band ? 4 : 128;
  node.height = 128;
  const ctx = node.getContext("2d");
  const color = rgb(light.color);
  const gradient = band ? ctx.createLinearGradient(0, 0, 0, 128) : ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  for (const [at, alpha] of band ? [[0, 0], [0.28, 0.45], [0.5, 1], [0.72, 0.45], [1, 0]] : [[0, 1], [0.45, 0.45], [1, 0]]) {
    gradient.addColorStop(at, rgba(color, alpha));
  }
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, node.width, node.height);
  const [x, y] = light.at;
  Object.assign(node.style, { left: `${x * 100}%`, top: `${y * 100}%`, animationDuration: `${16 + Math.random() * 12}s`,
    animationDelay: `${-Math.random() * 16}s` });
  if (band) Object.assign(node.style, { width: "300vmax", height: `${light.width * 100}vh`, rotate: `${light.angle ?? 0}deg` });
  else Object.assign(node.style, { width: `${light.size[0] * 100}vw`, height: `${light.size[1] * 100}vh` });
  node.style.setProperty("--o", (light.opacity ?? 0.3) * BRIGHTNESS.light);
  node.style.setProperty("--oc", (light.chorus ?? light.opacity ?? 0.3) * BRIGHTNESS.light);
  return node;
}

// --- the effects -----------------------------------------------------------------------------------

export function songEffects(player, { page, back, front }) {
  const visual = back.closest(".visual");
  const scenes = visual.querySelector(".scenes");
  const vignette = visual.querySelector(".visual-vignette");
  const builtScenes = new Map(); // look -> its scene, built the first time it shows and kept
  let shownScene = null; // the scene element showing (it gets --chorus and --swell)
  let varsAt = 0; // when the CSS variables were last set
  const view = { width: 0, height: 0, ratio: 1, scale: 1, density: 1 };
  let wanted = null; // the look for the song that's playing (null: it has none)
  let look = null; // the look on screen
  let sceneLook = null; // the look whose scene is in full screen
  let spans = []; // when the song's chorus plays: [start, end] in seconds
  let timing = chorusTiming(null, null); // how long it takes to come and go, in the song's time
  let particles = [];
  let rayMotion = []; // how each ray sways, brightens, and fades
  let level = 0; // how strongly the effects show, 0 to 1
  let chorus = 0; // how far the chorus look has taken over, 0 to 1
  let swell = 0; // the extra light around the drop: up to 1 on it, then fading to 0
  let pop = 0; // the light's pop right on the drop: up to POP, then ringing out
  let dark = 0; // how much of the light a break before a drop takes away: up to DARK
  // where the full-screen scene sits: half the player bar's height up while the bar shows, gliding
  // between (barAway: whether the bar was away last frame; null when not in full screen)
  let glide = { from: 0, to: 0, since: 0 };
  let barAway = null;
  let clock = 0; // seconds of animation, for wandering and shimmering
  let lastTime = 0; // the playback position at the last frame, to catch the chorus landing
  let lightPage = false;
  let frame = 0;
  let last = 0;
  const shownVars = {}; // the CSS variables last set, by name

  // from what the song does to what the chorus does, as far as the chorus has taken over
  const mix = (verse, inChorus) => (inChorus === undefined ? verse : verse + (inChorus - verse) * chorus);

  function lookFor(track) {
    const entry = track && SONG_EFFECTS[track.id];
    return (typeof entry === "string" ? SONG_EFFECTS[entry] : entry) || null;
  }

  function loadChorus(track) {
    spans = [];
    const own = track && SONG_EFFECTS[track.id];
    timing = chorusTiming(own, track);
    if (own?.chorusTimes) {
      setSpans(track, own.chorusTimes.map(span).filter(Boolean), "from song-effects.js");
      return;
    }
    loadAnalysis(track).then((data) => {
      if (data?.chorus && player.current?.id === track.id) setSpans(track, data.chorus, "found in its analysis");
    });
  }

  function setSpans(track, found, source) {
    spans = found;
    if (DEBUG && lookFor(track)) {
      const times = found.map(([start, end]) => `${clockTime(start)}-${clockTime(end)}`).join(", ") || "none";
      console.log(`[effects] ${track.id}: chorus ${times} (${source}); ${timing.about}`);
    }
  }

  // The song's scene, from the moment it's chosen (playing or not): the old one fades out as the new
  // one fades in, and the album's moving glows give way while a song has one (style.css). Each scene
  // is built once and kept: one that isn't showing isn't drawn, and showing it again only fades it in.
  function showScene(next) {
    if (next === sceneLook) return;
    sceneLook = next;
    for (const old of scenes.children) {
      if (!old.classList.contains("shown")) continue;
      old.classList.remove("shown");
      // once faded out it isn't kept up to date at all (style.css, .asleep)
      setTimeout(() => old.classList.contains("shown") || old.classList.add("asleep"), 1700);
    }
    shownScene = null;
    for (const name of ["--chorus", "--swell", "--dark"]) delete shownVars[name];
    visual.toggleAttribute("data-scene", Boolean(next?.scene));
    if (!next?.scene) return;
    let scene = builtScenes.get(next);
    if (!scene) {
      scene = document.createElement("div");
      scene.className = "scene asleep";
      scene.append(...next.scene.map(sceneLight));
      scenes.append(scene);
      builtScenes.set(next, scene);
    }
    shownScene = scene;
    // drawn transparent for a frame, then fading in, so it fades from nothing without the page
    // having to be laid out to find that out
    scene.classList.remove("asleep");
    const still = () => builtScenes.get(sceneLook) === scene;
    requestAnimationFrame(() => requestAnimationFrame(() => still() && scene.classList.add("shown")));
  }

  // --chorus and --swell for the scene, --vignette for the vignette, set only on what uses them (each
  // change restyles everything under the element it's set on), and only when they change by enough
  // to see, at most 30 times a second; style.css glides between the values.
  function setVar(name, value) {
    const text = value === null ? null : (Math.round(value * 200) / 200).toFixed(3);
    if (shownVars[name] === text) return;
    shownVars[name] = text;
    const node = name === "--vignette" ? vignette : shownScene;
    if (!node) return;
    if (text === null) node.style.removeProperty(name);
    else node.style.setProperty(name, text);
  }

  // All the canvases cover the whole window. Particles keep their place in it when it changes size.
  function measure() {
    const width = innerWidth;
    const height = innerHeight;
    if (view.width) {
      for (const p of particles) {
        p.x *= width / view.width;
        p.y *= height / view.height;
      }
    }
    const area = (width * height) / FULL_HD;
    Object.assign(view, {
      width,
      height,
      ratio: Math.min(devicePixelRatio || 1, MAX_PIXEL_RATIO[quality()]),
      scale: clamp(Math.sqrt(area), 0.6, 1.25),
      density: clamp(area, 0.35, 1.2) * DENSITY[quality()],
    });
  }

  function readTheme() {
    const [r, g, b] = (getComputedStyle(document.body).backgroundColor.match(/[\d.]+/g) || [0, 0, 0]).map(Number);
    lightPage = 0.2126 * r + 0.7152 * g + 0.0722 * b > 128;
  }

  const reach = () => Math.hypot(view.width, view.height) / 2; // from the middle to a corner

  // A new particle: anywhere on screen (or, for a burst from the center, in the middle with a push).
  // A few are in front of the cover in full screen.
  function spawn({ burst, fill } = {}) {
    const style = look.particles;
    const depth = style.depth ?? 0.5;
    const near = 1 + depth * (Math.random() - 0.5) * 1.2; // the far ones smaller, slower, fainter
    const colors = (burst || Math.random() < chorus) && look.chorus?.colors ? look.chorus.colors : style.colors;
    const spread = style.spread ?? 0;
    const p = {
      x: Math.random() * view.width,
      y: Math.random() * view.height,
      near,
      front: quality() === "high" && Math.random() < (style.front ?? FRONT),
      radius: between(style.size) * near,
      color: colors[Math.floor(Math.random() * colors.length)],
      jx: (Math.random() * 2 - 1) * spread, // its own speed, on top of the drift
      jy: (Math.random() * 2 - 1) * spread,
      kx: 0, // a burst's push
      ky: 0,
      vx: 0, // how fast it moved last frame (pixels a second), for streaks
      vy: 0,
      phase: Math.random() * TAU,
      wander: 0.2 + Math.random() * 0.4, // radians a second
      shimmer: 1.2 + Math.random() * 2.4,
      angle: Math.random() * TAU,
      spin: (Math.random() * 2 - 1) * (style.spin ?? 0) * TAU,
      age: 0,
      life: burst ? between([3, 5]) : between(style.life),
      fadeIn: burst ? timing.burstIn : FADE_IN_S,
      burst: Boolean(burst),
      leaving: false,
    };
    if (fill) p.age = Math.random() * p.life * 0.8;
    const center = burst?.from === "center";
    if (style.flow === "out") {
      // out from the middle: a direction, and how far along it
      p.dir = Math.random() * TAU;
      p.r = center ? Math.random() * 10 : Math.sqrt(Math.random()) * reach() * 0.9;
      p.kr = center ? (burst.speed ?? 150) * (0.4 + 0.6 * Math.random()) * view.scale : 0;
    } else if (center) {
      const angle = Math.random() * TAU;
      const push = (burst.speed ?? 150) * (0.4 + 0.6 * Math.random()) * view.scale;
      Object.assign(p, { x: view.width / 2, y: view.height / 2, kx: Math.cos(angle) * push, ky: Math.sin(angle) * push });
    }
    return p;
  }

  function wantedCount() {
    return Math.round(look.particles.count * view.density * mix(1, look.chorus?.count));
  }

  function start(next) {
    look = next;
    particles = [];
    chorus = 0;
    swell = 0;
    pop = 0;
    dark = 0;
    rayMotion = Array.from({ length: next?.rays ? next.rays.count ?? 3 : 0 }, () => ({
      phase: Math.random() * TAU,
      rate: 0.08 + Math.random() * 0.12, // how slowly it brightens and fades
      width: 0.6 + Math.random() * 0.8,
      lean: 1 + Math.random() * 2, // degrees it sways
    }));
    if (next) for (let i = wantedCount(); i > 0; i--) particles.push(spawn({ fill: true }));
  }

  // How far the chorus look, the swell, and the pop should be at a moment of the song: the look and
  // the swell build up over the measures and beats before each drop (slowly at first, faster toward
  // it, like a riser) and are complete on it; the pop rises on the drop and rings out. A bigger
  // chorus (its size above 1) takes all of them further. And a break before a drop (the music gone
  // for a beat or two) takes the light away at once, then brings it back up into the drop.
  function aroundTheChorus(time) {
    let build = 0;
    let light = 0;
    let hit = 0;
    let gone = 0;
    for (const [start, end, size = 1, breakBeats = 0] of spans) {
      const before = start - time;
      if (before > 0) {
        build = Math.max(build, size * (1 - Math.min(1, before / timing.build)) ** 2);
        light = Math.max(light, size * (1 - Math.min(1, before / timing.swellIn)) ** 2);
        const length = breakBeats * timing.beat;
        if (before < length) {
          const into = length - before;
          const fall = Math.min(DARK_IN_S, length / 4);
          gone = Math.max(gone, DARK * (into < fall ? into / fall : 1 - ease((into - fall) / (length - fall))));
        }
      } else {
        build = Math.max(build, size * (time < end ? 1 : 1 - ease((time - end) / timing.fall)));
        light = Math.max(light, size * Math.exp((3 * before) / SWELL_S));
        const since = -before;
        hit = Math.max(hit, size * POP * (since < POP_IN_S ? since / POP_IN_S : Math.exp(-(since - POP_IN_S) / POP_S)));
      }
    }
    return [build, light, hit, gone];
  }

  // The chorus look follows the playback position (catching up gradually after a jump). Passing the
  // moment a burst should start, while playing, starts it.
  function followChorus(dt, time) {
    const [build, light, hit, gone] = aroundTheChorus(time);
    chorus += clamp(build - chorus, -dt / CATCH_S, dt / CATCH_S);
    swell += clamp(light - swell, (-3 * dt) / CATCH_S, (3 * dt) / CATCH_S);
    pop = hit;
    dark = gone; // (at once: a break is a beat or two)
    if (!player.playing || time <= lastTime || time - lastTime > 1) return; // paused, or a jump
    if (DEBUG && spans.some(([a]) => lastTime < a && time >= a)) console.log(`[effects] the chorus lands at ${clockTime(time)}`);
    const landing = spans.find(([a]) => lastTime < a - timing.burstIn && time >= a - timing.burstIn);
    const burst = landing && look.chorus?.burst;
    if (burst) for (let i = Math.round(burst.count * (landing[2] ?? 1) * view.density); i > 0; i--) particles.push(spawn({ burst }));
  }

  function update(dt) {
    const style = look.particles;
    const chorusLook = look.chorus || {};
    const speed = mix(1, chorusLook.speed) * (1 + 0.2 * swell);
    const [dx, dy] = style.drift ?? [0, 0];
    const driftX = mix(dx, chorusLook.drift?.[0]);
    const driftY = mix(dy, chorusLook.drift?.[1]);
    const cx = view.width / 2;
    const cy = view.height / 2;
    const far = reach();
    // in the chorus, some looks circle around the middle (the cover), as the chorus comes in
    const swirl = (chorusLook.swirl ?? 0) * chorus * (1 + 0.2 * swell) * view.scale;
    const margin = 120; // room for the big ones in front to leave the screen before they wrap around
    const decay = Math.exp(-dt / KICK_S);
    let count = 0;
    for (const p of particles) {
      p.age += dt;
      p.angle += p.spin * dt;
      const pace = speed * (p.front ? FRONT_SPEED : 1);
      if (style.flow === "out") {
        // faster the further out, like passing them
        const v = ((style.speed ?? 10) + p.jx) * (0.15 + (1.6 * p.r) / far) * p.near * view.scale * pace + p.kr;
        p.kr *= decay;
        p.r += v * dt;
        p.vx = Math.cos(p.dir) * v;
        p.vy = Math.sin(p.dir) * v;
        p.x = cx + Math.cos(p.dir) * p.r;
        p.y = cy + Math.sin(p.dir) * p.r;
        if (p.r > far + margin) p.age = p.life; // off screen: done
      } else {
        p.vx = (driftX + p.jx) * p.near * view.scale * pace + p.kx;
        p.vy = (driftY + p.jy) * p.near * view.scale * pace + p.ky;
        if (swirl) {
          // around the middle, counterclockwise, the inner ones a little faster
          const dx = p.x - cx;
          const dy = p.y - cy;
          const r = Math.hypot(dx, dy) || 1;
          const v = swirl * (0.7 + 0.6 * Math.max(0, 1 - r / far)) * p.near * (p.front ? FRONT_SPEED : 1);
          p.vx += (dy / r) * v;
          p.vy -= (dx / r) * v;
        }
        p.kx *= decay;
        p.ky *= decay;
        p.x += p.vx * dt;
        p.y += p.vy * dt;
        // off one side, back in on the other
        if (p.x < -margin) p.x += view.width + 2 * margin;
        else if (p.x > view.width + margin) p.x -= view.width + 2 * margin;
        if (p.y < -margin) p.y += view.height + 2 * margin;
        else if (p.y > view.height + margin) p.y -= view.height + 2 * margin;
      }
      if (!p.burst && !p.leaving && p.age < p.life) count++;
    }
    particles = particles.filter((p) => p.age < p.life);
    // keep as many as the moment calls for: new ones fade in, extra ones fade out
    const target = wantedCount();
    for (; count < target; count++) particles.push(spawn());
    for (const p of particles) {
      if (count <= target) break;
      if (p.burst || p.leaving) continue;
      p.leaving = true;
      p.life = Math.min(p.life, p.age + between([1.5, 3]));
      count--;
    }
  }

  // --- drawing ---------------------------------------------------------------------------------

  // How far the full-screen scene (and the cover) is moved up, in pixels, as style.css moves it: half
  // the player bar's height while the bar shows, none while it's away, gliding over GLIDE_S between.
  // (The bar's height is read only when it comes or goes.)
  function sceneShift(now) {
    const at = (time) => glide.from + (glide.to - glide.from) * easeOut(clamp((time - glide.since) / (GLIDE_S * 1000), 0, 1));
    const away = document.body.classList.contains("controls-hidden");
    if (away !== barAway) {
      const to = away ? 0 : -parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--bar-h") || 0) / 2;
      // (a CSS transition starts on the frame after the change, so the rays start a frame later too;
      // just opened, the scene is already there)
      glide = { from: barAway === null ? to : at(now), to, since: now + 1000 / 60 };
      barAway = away;
    }
    return at(now);
  }

  // shift: how far up the rays are moved (in full screen, with the scene they shine from)
  function drawRays(ctx, strength, light, shift = 0) {
    const rays = look.rays;
    const opacity = rays && mix(rays.opacity ?? 0, look.chorus?.rays) * (1 + 0.4 * (swell + pop)) * BRIGHTNESS.light * strength;
    if (!opacity || opacity < 0.002) return;
    const image = sprite("beam", rays.color, light);
    const x = rays.from[0] * view.width;
    const y = rays.from[1] * view.height + shift;
    const length = (rays.length ?? 1.2) * reach() * 2;
    const k = view.ratio;
    rayMotion.forEach((ray, i) => {
      const along = rayMotion.length > 1 ? i / (rayMotion.length - 1) - 0.5 : 0;
      const degrees = (rays.angle ?? 90) + (rays.spread ?? 0) * along + ray.lean * Math.sin(clock * 0.06 + ray.phase);
      const angle = (degrees * Math.PI) / 180 - Math.PI / 2; // the beam is drawn pointing down
      const width = (rays.width ?? 120) * ray.width * view.scale;
      ctx.globalAlpha = Math.min(1, opacity * (0.55 + 0.45 * Math.sin(clock * ray.rate + ray.phase)));
      const cos = Math.cos(angle);
      const sin = Math.sin(angle);
      ctx.setTransform(cos * k, sin * k, -sin * k, cos * k, x * k, y * k);
      ctx.drawImage(image, -width / 2, 0, width, length);
    });
  }

  // which: "back" (behind the cover), "front" (in front of it), or "all" (behind the page)
  function drawParticles(ctx, strength, light, which) {
    const style = look.particles;
    const shape = style.shape ?? "dot";
    const opacity = (style.opacity ?? 0.5) * mix(1, look.chorus?.opacity) * (1 + 0.4 * swell) * BRIGHTNESS.particles * strength;
    const grow = mix(1, look.chorus?.size) * view.scale * 2 * (EXTENT[shape] ?? 3);
    const stretch = mix(style.stretch ?? 0, look.chorus?.stretch);
    const sway = style.sway ?? 0;
    const twinkle = style.twinkle ?? 0;
    const k = view.ratio;
    for (const p of particles) {
      if ((which === "back" && p.front) || (which === "front" && !p.front)) continue;
      const fade = ease(p.age / p.fadeIn) * ease((p.life - p.age) / 1.5);
      const shimmer = 1 - twinkle * (0.5 + 0.5 * Math.sin(clock * p.shimmer + p.phase));
      const alpha = Math.min(1, opacity * fade * shimmer * (0.75 + 0.25 * p.near) * (p.front ? FRONT_ALPHA : 1));
      if (alpha < 0.004) continue;
      ctx.globalAlpha = alpha;
      const image = sprite(shape, p.color, light, p.front);
      // out along its path, with a slow wander around it
      const wander = sway * (p.front ? FRONT_SPEED : 1);
      const x = p.x + wander * Math.sin(clock * p.wander + p.phase);
      const y = p.y + wander * 0.6 * Math.cos(clock * p.wander * 0.8 + p.phase * 1.3);
      let size = p.radius * grow;
      if (p.front) size *= FRONT_SIZE * (1 + 2 * SOFT_PAD); // the soft shape has room around it for its blur
      if (style.flow === "out") size *= 0.6 + (0.8 * p.r) / reach(); // nearer, so bigger, as they come out
      const speed = Math.hypot(p.vx, p.vy);
      if (stretch > 0 && speed > 1) {
        // a streak along its motion, thinner than the particle
        const length = size * (1 + (stretch * speed) / (p.front ? FRONT_SPEED : 1));
        const cos = p.vx / speed;
        const sin = p.vy / speed;
        ctx.setTransform(cos * k, sin * k, -sin * k, cos * k, x * k, y * k);
        ctx.drawImage(image, -length / 2, -size * 0.3, length, size * 0.6);
      } else if (shape === "shard" || shape === "petal") {
        // turning; a petal also tumbles, so it narrows and widens
        const flip = shape === "petal" ? 0.3 + 0.7 * Math.abs(Math.cos(clock * p.wander * 1.5 + p.phase)) : 1;
        const cos = Math.cos(p.angle);
        const sin = Math.sin(p.angle);
        ctx.setTransform(cos * k * flip, sin * k * flip, -sin * k, cos * k, x * k, y * k);
        ctx.drawImage(image, -size / 2, -size / 2, size, size);
      } else {
        ctx.setTransform(k, 0, 0, k, 0, 0);
        ctx.drawImage(image, x - size / 2, y - size / 2, size, size);
      }
    }
  }

  // A canvas sized to the window and cleared, ready to draw on.
  function prepare(canvas, light) {
    const width = Math.round(view.width * view.ratio);
    const height = Math.round(view.height * view.ratio);
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.globalCompositeOperation = light ? "source-over" : "lighter"; // light adds up, like light does
    return ctx;
  }

  function render() {
    const full = visual.classList.contains("open");
    for (const canvas of full ? [page] : [back, front]) if (canvas.width) release(canvas);
    const shown = level * (1 - dark); // a break before a drop takes the light away
    if (full) {
      drawParticles(prepare(back, false), shown, false, "back");
      const ctx = prepare(front, false);
      drawRays(ctx, shown, false, sceneShift(performance.now()));
      drawParticles(ctx, shown, false, "front");
    } else {
      barAway = null;
      const ctx = prepare(page, lightPage);
      const strength = shown * PAGE_STRENGTH * (lightPage ? LIGHT_STRENGTH : 1);
      drawRays(ctx, strength, lightPage);
      drawParticles(ctx, strength, lightPage, "all");
    }
    // the scene brightens with the chorus and the landing, and goes dark in a break; the vignette
    // lifts (stronger than usual otherwise, for a moodier verse, and in a break)
    if (performance.now() - varsAt < 33) return;
    varsAt = performance.now();
    setVar("--chorus", chorus * level);
    setVar("--swell", (swell + pop) * level);
    setVar("--dark", dark * level);
    setVar("--vignette", clamp(VIGNETTE + level * (0.18 - 0.6 * chorus - 0.15 * (swell + pop) + 0.4 * dark), 0.15, 1));
  }

  // an empty canvas holds no memory
  function release(canvas) {
    canvas.width = 0;
    canvas.height = 0;
  }

  function tick(now) {
    // a new picture only as often as this view needs one
    const every = quality() === "low" ? FRAME_MS.low : visual.classList.contains("open") ? FRAME_MS.full : FRAME_MS.page;
    if (now - last < every - 4) {
      frame = requestAnimationFrame(tick);
      return;
    }
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    const time = player.time;
    const on = Boolean(wanted) && player.playing && graphics() !== "off";
    if (look !== wanted) {
      level = Math.max(0, level - dt / SWAP_S);
      if (level === 0) start(wanted);
    } else {
      level = clamp(level + (on ? dt : -dt) / FADE_S, 0, 1);
    }
    if (look && level > 0) {
      clock += dt;
      followChorus(dt, time);
      update(dt);
      render();
    }
    lastTime = time;
    if (on || level > 0) {
      frame = requestAnimationFrame(tick);
    } else {
      frame = 0;
      for (const canvas of [page, back, front]) release(canvas);
      for (const name of ["--chorus", "--swell", "--dark", "--vignette"]) setVar(name, null);
      barAway = null; // where the scene is gets looked at afresh next time
    }
  }

  function wake() {
    if (frame) return;
    last = performance.now();
    frame = requestAnimationFrame(tick);
  }

  function follow(track) {
    wanted = lookFor(track);
    showScene(graphics() === "off" ? null : wanted);
    loadChorus(track);
    lastTime = player.time;
  }

  // A new graphics setting: new numbers, the particles started again with them, and the scene
  // taken away (Off) or brought back.
  function regraphic() {
    measure();
    if (look && graphics() !== "off") start(look);
    showScene(graphics() === "off" ? null : wanted);
    wake();
  }

  measure();
  readTheme();
  for (const canvas of [page, back, front]) release(canvas);
  addEventListener("resize", measure);
  new MutationObserver(readTheme).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  matchMedia("(prefers-color-scheme: light)").addEventListener("change", readTheme);
  onSettingsChange((what) => what === "graphics" && regraphic());
  player.addEventListener("change", ({ detail }) => {
    if (detail === "track") follow(player.current);
    if (detail === "track" || detail === "state") wake();
  });
  follow(player.current);
  wake();
  if (graphics() !== "off") prewarm();
}
