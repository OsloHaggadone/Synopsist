// The listener's settings, kept in this browser: the site's colors (a theme from one of the albums'
// covers: Hollow Journey, the default, Hollow Journey Beyond, Planetary Fields, or Eternal
// Synopsis), light, dark, or following the device (Auto), and how much the site moves and glows
// (graphics): High (everything), Low (lighter, for slower devices), or Off (no moving backgrounds or
// song effects). index.html's first script applies them before the page is drawn, as data-palette,
// data-theme, and data-graphics on <html>; this module changes them and tells the rest of the site.
// A device that asks for less motion always gets Off. And the sound: an EQ preset (js/eq.js),
// whether the live EQ shows along the bottom of the screen (js/liveeq.js), whether the songs play
// evened out in loudness (Enhance audio, on unless turned off) or as mastered, and whether one song
// fades into the next (off unless turned on; both in js/eq.js). Whether songs can be
// rated out of five stars (off unless turned on; the ratings themselves are in js/marks.js). And
// how the music page orders the songs, and which albums it shows folded.

const PALETTE_KEY = "synopsist.palette";
const THEME_KEY = "synopsist.theme";
const GRAPHICS_KEY = "synopsist.graphics";
const EQ_KEY = "synopsist.eq";
const LIVE_EQ_KEY = "synopsist.liveEq";
const ENHANCE_KEY = "synopsist.enhance"; // "0" once turned off (it's on unless it is)
const FADE_KEY = "synopsist.fade";
const SORT_KEY = "synopsist.sort";
const RATINGS_KEY = "synopsist.showRatings";
const COLLAPSED_KEY = "synopsist.collapsed";
export const PALETTES = ["hollow-journey", "hollow-journey-beyond", "planetary-fields", "eternal-synopsis"];
export const THEMES = ["auto", "light", "dark"];
export const GRAPHICS = ["high", "low", "off"];
export const EQS = ["flat", "bass-boost", "bass-reduce", "treble-boost", "vocal-boost", "electronic", "rnb", "small-speakers"];
export const SORTS = ["albums", "popular", "newest", "title", "artist", "favorites", "playlists"];

const root = document.documentElement;
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
const listeners = new Set();

function remember(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // storage blocked: the choice lasts until the page is closed
  }
}

function recall(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function changed(what) {
  for (const listener of listeners) listener(what);
}

let eq = EQS.includes(recall(EQ_KEY)) ? recall(EQ_KEY) : EQS[0];
let liveEq = recall(LIVE_EQ_KEY) === "1";
let enhance = recall(ENHANCE_KEY) !== "0";
let fade = recall(FADE_KEY) === "1";
let sort = SORTS.includes(recall(SORT_KEY)) ? recall(SORT_KEY) : SORTS[0];
let showRatings = recall(RATINGS_KEY) === "1";
let collapsed;
try {
  collapsed = new Set([].concat(JSON.parse(recall(COLLAPSED_KEY)) ?? []));
} catch {
  collapsed = new Set(); // something unreadable: every album open
}

// The listener's choices.
export const paletteSetting = () => (PALETTES.includes(root.dataset.palette) ? root.dataset.palette : PALETTES[0]);
export const themeSetting = () => (root.dataset.theme === "light" || root.dataset.theme === "dark" ? root.dataset.theme : "auto");
export const graphicsSetting = () => (GRAPHICS.includes(root.dataset.graphics) ? root.dataset.graphics : "high");
export const eqSetting = () => eq;
export const liveEqSetting = () => liveEq;
export const enhanceSetting = () => enhance; // every song about as loud as the others (js/eq.js)
export const fadeSetting = () => fade; // one song fading into the next (js/eq.js)
export const sortSetting = () => sort;
export const ratingsSetting = () => showRatings;
export const isCollapsed = (album) => collapsed.has(album);

// What the site does: the choice, unless the device asks for less motion.
export const graphics = () => (reduceMotion.matches ? "off" : graphicsSetting());
export const motionReduced = () => reduceMotion.matches;

export function setPalette(palette) {
  if (palette === PALETTES[0]) delete root.dataset.palette;
  else root.dataset.palette = palette;
  remember(PALETTE_KEY, palette === PALETTES[0] ? null : palette);
  changed("palette");
}

export function setTheme(mode) {
  if (mode === "auto") delete root.dataset.theme;
  else root.dataset.theme = mode;
  remember(THEME_KEY, mode === "auto" ? null : mode);
  changed("theme");
}

export function setGraphics(level) {
  if (level === "high") delete root.dataset.graphics;
  else root.dataset.graphics = level;
  remember(GRAPHICS_KEY, level === "high" ? null : level);
  changed("graphics");
}

export function setEq(preset) {
  eq = EQS.includes(preset) ? preset : EQS[0];
  remember(EQ_KEY, eq === EQS[0] ? null : eq);
  changed("eq");
}

export function setLiveEq(on) {
  liveEq = on;
  remember(LIVE_EQ_KEY, on ? "1" : null);
  changed("liveEq");
}

export function setEnhance(on) {
  enhance = on;
  remember(ENHANCE_KEY, on ? null : "0");
  changed("enhance");
}

export function setFade(on) {
  fade = on;
  remember(FADE_KEY, on ? "1" : null);
  changed("fade");
}

export function setSort(order) {
  sort = SORTS.includes(order) ? order : SORTS[0];
  remember(SORT_KEY, sort === SORTS[0] ? null : sort);
  changed("sort");
}

export function setRatings(on) {
  showRatings = on;
  remember(RATINGS_KEY, on ? "1" : null);
  changed("ratings");
}

// An album folded to its heading in the music page's list, or opened again (the page does the
// showing itself, so nothing is told).
export function setCollapsed(album, folded) {
  if (folded) collapsed.add(album);
  else collapsed.delete(album);
  remember(COLLAPSED_KEY, collapsed.size ? JSON.stringify([...collapsed]) : null);
}

// fn("palette" | "theme" | "graphics" | "eq" | "liveEq" | "enhance" | "fade" | "ratings" | "sort"), whenever one changes
// (graphics too when the device's motion setting does)
export function onSettingsChange(fn) {
  listeners.add(fn);
}

reduceMotion.addEventListener("change", () => changed("graphics"));
