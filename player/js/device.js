// Settings > Graphics recommends a level for this device. A first guess comes from what the browser
// tells about it: its graphics card (as WebGL names it), its processor's cores, its memory, and its
// screen. Built-in graphics (Intel's, AMD's in a laptop, a phone's) get Low, a graphics card of its
// own (or Apple's) High, and a browser drawing without one, Off. Then what really happened outweighs
// the guess: while the full-screen view (the most the site draws) is open and the music plays, the
// frames the page gets each second are counted, for the graphics level in use, and kept in this
// browser (synopsist.performance). Smooth on High, it's High; not, Low; and rough even on Low, Off.
// Nothing leaves the browser, and nothing is changed until the listener says so.

import { graphics } from "./settings.js";

const PERF_KEY = "synopsist.performance";
const SMOOTH_FPS = 50; // full screen this smooth on High (frames a second) or better: High is right,
const ROUGH_FPS = 28; // and this rough on Low or worse: Off is better
const MEASURED_S = 10; // a level's frame rate counts once it's been seen this long
const WARM_UP_MS = 2500; // the view's first moments aren't counted (it fades in, the cover unfolds),
const STRETCH_MS = 5000; // the frames are counted in stretches this long,
const MEMORY_S = 60; // and the latest minute or so of them counts most
const BIG_SCREEN = 2560 * 1600; // more pixels than this is a lot to draw without a strong graphics card

const SOFTWARE = /swiftshader|llvmpipe|softpipe|software|basic render/i;
const OWN_CARD = /nvidia|geforce|quadro|rtx|gtx|radeon (rx|pro|r9)|\barc a\d|apple (m\d|gpu)/i;
const BUILT_IN = /intel|radeon.*graphics|vega|adreno|mali|powervr|videocore/i;

// The graphics card's name as people know it:
// "ANGLE (Intel, Intel(R) UHD Graphics 620 (0x00005917) Direct3D11 vs_5_0 ps_5_0, D3D11)" -> "Intel UHD Graphics 620"
export function cardName(raw) {
  const named = /^ANGLE \((.*)\)$/.exec(raw)?.[1].split(", ")[1] ?? raw;
  return named
    .replace(/^ANGLE Metal Renderer: /, "")
    .replace(/\((R|TM)\)/gi, "")
    .replace(/\s*\(0x[\da-f]+\)/gi, "")
    .replace(/\s+(Direct3D|OpenGL|Vulkan|Metal|vs_\d).*$/i, "")
    .replace(/^Mesa\s+/, "")
    .replace(/\s*\([^)]*\)$/, "") // "(KBL GT2)"
    .replace(/\/.*$/, "") // "GeForce GTX 1050/PCIe/SSE2"
    .replace(/\s+/g, " ")
    .trim();
}

// "software" | "own" (a graphics card of its own, or Apple's) | "built-in" | "unknown"
export function cardKind(raw, software = false) {
  if (software || SOFTWARE.test(raw)) return "software";
  if (OWN_CARD.test(raw)) return "own";
  if (BUILT_IN.test(raw)) return "built-in";
  return "unknown";
}

// What WebGL says the graphics card is, and whether the browser draws without one (it then refuses
// a context that would be slow). Null when WebGL is off or missing.
function graphicsCard() {
  try {
    const fast = document.createElement("canvas").getContext("webgl", { failIfMajorPerformanceCaveat: true });
    const gl = fast ?? document.createElement("canvas").getContext("webgl");
    if (!gl) return null;
    const info = gl.getExtension("WEBGL_debug_renderer_info");
    const raw = String(gl.getParameter(info ? info.UNMASKED_RENDERER_WEBGL : gl.RENDERER));
    gl.getExtension("WEBGL_lose_context")?.loseContext(); // done with it
    return { raw, software: !fast };
  } catch {
    return null;
  }
}

let device = null;

// The device, as the browser tells it (worked out once: it takes a moment, so not while the page
// loads).
export function aboutDevice() {
  if (device) return device;
  const card = graphicsCard();
  device = {
    card: card ? cardName(card.raw) : "",
    kind: card ? cardKind(card.raw, card.software) : "unknown",
    cores: navigator.hardwareConcurrency || 0,
    memory: navigator.deviceMemory || 0, // in GB (Chrome and Edge only)
    width: Math.round(screen.width * devicePixelRatio),
    height: Math.round(screen.height * devicePixelRatio),
  };
  return device;
}

// How the full-screen view ran here, by graphics level: {high: {fps, seconds}, low: ...}.
function measured() {
  try {
    return JSON.parse(localStorage.getItem(PERF_KEY)) ?? {};
  } catch {
    return {};
  }
}

// The frame rates seen long enough to go by, by graphics level: {high: 57, low: 60}.
export function frameRates() {
  return Object.fromEntries(Object.entries(measured()).filter(([, seen]) => seen.seconds >= MEASURED_S).map(([level, seen]) => [level, seen.fps]));
}

function record(level, fps, seconds) {
  const all = measured();
  const before = all[level] ?? { fps, seconds: 0 };
  const weight = Math.min(before.seconds, MEMORY_S);
  all[level] = { fps: Math.round((before.fps * weight + fps * seconds) / (weight + seconds)), seconds: Math.round(weight + seconds) };
  try {
    localStorage.setItem(PERF_KEY, JSON.stringify(all));
  } catch {
    // storage blocked: nothing is kept
  }
}

// The graphics level for this device: "high", "low", or "off".
export function recommendation() {
  const { kind, cores, memory, width, height } = aboutDevice();
  let level = kind === "software" ? "off"
    : kind === "own" ? "high"
    : kind === "built-in" ? "low"
    : cores >= 8 && width * height <= BIG_SCREEN ? "high" : "low";
  if (level === "high" && ((cores && cores <= 2) || (memory && memory <= 2))) level = "low";
  // what full screen really managed, over the guess
  const seen = frameRates();
  if (seen.high) level = seen.high >= SMOOTH_FPS ? "high" : "low";
  else if (seen.low && level === "off") level = "low"; // it ran on Low after all (and how well, next)
  if (level === "low" && seen.low < ROUGH_FPS) level = "off";
  return level;
}

// Counts the frames while the full-screen view is open and the music plays (isFull() says whether
// the view is open; check() when it opens or closes). It only listens for the frames as the page
// draws them, which costs nothing to speak of.
export function countFrames(player, isFull) {
  let frame = 0;
  let last = 0;
  let since = 0;
  let frames = 0;
  let time = 0;
  const on = () => isFull() && player.playing && graphics() !== "off" && !document.hidden;

  function tick(now) {
    if (!on()) {
      frame = 0;
      return;
    }
    const gap = now - last;
    last = now;
    if (now - since > WARM_UP_MS && gap < 250) {
      // (a longer gap: the page was away)
      frames += 1;
      time += gap;
    }
    if (time >= STRETCH_MS) {
      record(graphics(), (frames * 1000) / time, time / 1000);
      frames = 0;
      time = 0;
    }
    frame = requestAnimationFrame(tick);
  }

  function check() {
    if (frame || !on()) return;
    since = last = performance.now();
    frames = 0;
    time = 0;
    frame = requestAnimationFrame(tick);
  }

  player.addEventListener("change", ({ detail }) => detail === "state" && check());
  document.addEventListener("visibilitychange", check);
  return { check };
}
