// The website: the landing page, the music page (a song-select screen: the song playing beside the
// songs, album by album), the settings page, the player bar, the side panels (the queue, and a
// song's details), and the full-screen view, connected to the playback engine (player.js).
//
// The pages live in this one document so the music never stops between them: no "#" in the address
// shows the landing page, "#settings" the settings, and any other link ("#music", "#song-space-rain")
// the music page. Changing page cross-fades quickly, as changing the theme, or between light and
// dark, does.

import { SITE } from "../site.js";
import { loadAnalysis } from "./analysis.js";
import { markMoment, renderDetails } from "./details.js";
import { aboutDevice, countFrames, frameRates, recommendation } from "./device.js";
import { clock, el, icon, replay, restart, setIcon } from "./dom.js";
import { dropdown } from "./dropdown.js";
import { songEffects } from "./effects.js";
import { equalize } from "./eq.js";
import { setSharing, sharingEnabled } from "./listening.js";
import { liveEq } from "./liveeq.js";
import { loadNotes } from "./notes.js";
import { Player } from "./player.js";
import {
  eqSetting, graphics, graphicsSetting, liveEqSetting, motionReduced, onSettingsChange, paletteSetting, setEq, setGraphics,
  setLiveEq, setPalette, setSort, setTheme, sortSetting, themeSetting,
} from "./settings.js";
import { followTheMusic } from "./vibe.js";
import { wavePaths } from "./wave.js";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => document.querySelectorAll(selector);
const CATALOG_URL = new URL("library/catalog.json", document.baseURI);
const SEEK_STEP_S = 5;
const IDLE_MS = 2500; // in full screen, hide the pointer and the controls after this long without moving
const LINK_NAMES = { spotify: "Spotify", appleMusic: "Apple Music", amazonMusic: "Amazon Music", youtube: "YouTube", instagram: "Instagram", tiktok: "TikTok" };
const prefersLight = matchMedia("(prefers-color-scheme: light)");

let player;
let albums; // id -> album
let tracks; // id -> track
let allIds = []; // every song, album by album (the music page's usual order)
let focusId = null; // the song shown in the focus panel
let panel = null; // the side panel that's open: "queue", "details", or null
let detailsId = null; // the song in the details panel
let detailsFollow = false; // whether the details panel follows the song that's playing
let wasPlaying = false;

// --- small helpers ---------------------------------------------------------------------------

function totalTime(seconds) {
  const m = Math.round(seconds / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} hr ${m % 60} min`;
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const twoDigits = (n) => String(n).padStart(2, "0");
const searchable = (text) => text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

// Album art, or a cover drawn in the album's own colors when there's no image yet.
function coverArt(album, large = false) {
  const src = large ? album.cover_large || album.cover : album.cover;
  if (src) return el("img", { class: "cover-img", src, alt: "", loading: large ? "eager" : "lazy", decoding: "async" });
  const art = el("div", { class: "cover-art" }, el("span", {}, album.title));
  art.style.setProperty("--c1", album.colors[0]);
  art.style.setProperty("--c2", album.colors[1]);
  return art;
}

let toastTimer;
function toast(message) {
  const box = $("#toast");
  box.textContent = message;
  box.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.classList.remove("show"), 2600);
}

// --- the colors: a theme from an album cover, light or dark -------------------------------------

function currentTheme() {
  return document.documentElement.dataset.theme || (prefersLight.matches ? "light" : "dark");
}

// The browser's own bars (on phones) take the page's color.
function showTheme() {
  $('meta[name="theme-color"]').content = getComputedStyle(document.body).backgroundColor;
}

// A quick cross-fade while the page or the colors change, where the browser can.
function crossFade(change) {
  if (!document.startViewTransition || graphics() === "off") {
    change();
    return;
  }
  const root = document.documentElement;
  root.classList.add("cross-fading");
  document.startViewTransition(change).finished.finally(() => root.classList.remove("cross-fading"));
}

// Light, dark, or Auto (following the device).
function chooseTheme(mode) {
  if (mode === themeSetting()) return;
  const after = mode === "auto" ? (prefersLight.matches ? "light" : "dark") : mode;
  const apply = () => {
    setTheme(mode);
    showTheme();
  };
  if (after === currentTheme()) apply(); // the colors stay as they are
  else crossFade(apply);
}

// One of the album themes.
function choosePalette(palette) {
  if (palette === paletteSetting()) return;
  crossFade(() => {
    setPalette(palette);
    showTheme();
  });
}

// --- the settings page: the colors, how much the site moves, listening data (js/settings.js) ----

const choices = {}; // the dropdowns: palette (the theme), mode (light or dark), graphics, eq

// Each dropdown and switch shows what's chosen.
function showSettings() {
  choices.palette.show(paletteSetting());
  choices.mode.show(themeSetting());
  choices.graphics.show(graphicsSetting());
  choices.eq.show(eqSetting());
  $("#live-eq-setting").checked = liveEqSetting();
  $("#motion-note").hidden = !motionReduced(); // the device asks for less motion: Off, whatever is chosen
  $("#live-eq-note").hidden = !liveEqSetting() || graphics() !== "off";
  showAdvice();
}

const LEVELS = { high: "High", low: "Low", off: "Off" };
let deviceKnown = false; // the device is looked at once, in an idle moment after the page loads

// Under Graphics: the level recommended for this device (js/device.js), tagged in the list too, with
// a button to use it, and what it's based on. Not while the device asks for less motion (it's Off
// then, whatever is chosen).
function showAdvice() {
  const shown = deviceKnown && !motionReduced();
  $("#graphics-advice").hidden = !shown;
  $("#graphics-device").hidden = !shown;
  if (!shown) return;
  const level = recommendation();
  const inUse = graphicsSetting() === level;
  $("#graphics-advice-text").replaceChildren("Recommended for this device: ", el("b", {}, LEVELS[level]), inUse ? " (in use)" : "");
  $("#graphics-advice-use").hidden = inUse;
  $("#graphics-advice-use").textContent = `Use ${LEVELS[level]}`;
  for (const option of $$("#graphics-list [role=option]")) option.querySelector(".option-tag").hidden = option.dataset.value !== level;
  const { card, kind, cores, memory, width, height } = aboutDevice();
  const seen = frameRates();
  const ran = seen[graphicsSetting()] ? graphicsSetting() : Object.keys(seen)[0];
  $("#graphics-device").textContent = [
    kind === "software" ? "Drawing without a graphics card" : card ? `${card}${kind === "built-in" ? ", built in" : ""}` : "Graphics card unknown",
    cores && `${cores} cores`,
    memory && `${memory} GB memory`,
    `${width} × ${height} screen`,
    ran && `full screen ran at ${seen[ran]} frames a second on ${LEVELS[ran]}`,
  ].filter(Boolean).join(" · ");
}

// Sharing listening data: the switch on the settings page and the one in the privacy note are the
// same setting.
function wireSharing() {
  const switches = [$("#share-listening"), $("#share-listening-settings")];
  for (const box of switches) {
    box.checked = sharingEnabled();
    box.addEventListener("change", () => {
      setSharing(box.checked);
      for (const other of switches) other.checked = box.checked;
      toast(box.checked ? "Thanks! Sharing anonymous listening data" : "Listening data sharing is off");
    });
  }
}

// Works before the music has loaded (and if it can't), so it's wired first.
function wireSettings() {
  choices.palette = dropdown($("#palette-choice"), choosePalette);
  choices.mode = dropdown($("#mode-choice"), chooseTheme);
  choices.graphics = dropdown($("#graphics-choice"), setGraphics);
  choices.eq = dropdown($("#eq-choice"), setEq);
  $("#live-eq-setting").addEventListener("change", (event) => setLiveEq(event.target.checked));
  $("#graphics-advice-use").addEventListener("click", () => setGraphics(recommendation()));
  // iPhones and iPads (an iPad says it's a Mac, but one with a touch screen)
  $("#ios-sound-note").hidden = !/iP(hone|ad|od)/.test(navigator.userAgent) && !(navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  onSettingsChange(showSettings);
  showSettings();
  wireSharing();
}

// --- the pages -------------------------------------------------------------------------------

let backTo = ""; // where the settings page's Back goes: the landing page (""), or the music page
let musicScroll = null; // how far down the music page was when the settings opened
const jump = (y) => window.scrollTo({ top: y, behavior: "instant" });

function showView(firstLoad) {
  const hash = decodeURIComponent(location.hash.slice(1));
  const view = hash === "settings" ? "settings" : hash ? "player" : "home";
  const from = document.body.dataset.view;
  const switching = from !== view;
  if (view === "settings" && switching) {
    backTo = from === "home" ? "" : "music";
    musicScroll = from === "player" ? window.scrollY : null;
  }
  const apply = () => {
    document.body.dataset.view = view;
    for (const link of $$(".settings-link")) {
      if (view === "settings") link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
    if (view !== "player") {
      setPanel(null);
      jump(0);
    }
    if (view === "home") {
      if (switching || !$("#landing").classList.contains("intro")) restart($("#landing"), "intro");
      return;
    }
    if (view === "settings") {
      $("#settings-back").href = `#${backTo}`;
      showSettings(); // (how full screen has been running may have changed the advice)
      return;
    }
    // back from the settings: the music page where it was
    if (from === "settings" && hash === "music" && musicScroll !== null) {
      jump(musicScroll);
      musicScroll = null;
      return;
    }
    goTo(hash, switching || firstLoad);
  };
  if (!switching || firstLoad) apply();
  else crossFade(apply); // just a quick fade: the user found the old sweep of panels and rows too much
}

// Land on what a link points at: a song (loaded, ready to play), an album ("#album-hollow-journey"),
// or a section.
function goTo(hash, scroll) {
  if (hash.startsWith("album-") && sortSetting() !== "albums") setSort("albums"); // its heading is only there
  const target = document.getElementById(hash);
  if (target?.closest("#albums [hidden]")) {
    $("#search").value = ""; // the search was hiding it
    filterSongs();
  }
  if (hash.startsWith("song-") && tracks?.has(hash.slice(5))) {
    const id = hash.slice(5);
    const album = albums.get(tracks.get(id).album);
    if (player.current?.id !== id) player.playList(album.tracks, { start: id, label: album.title, autoplay: false });
    restart(target, "highlight");
    target.scrollIntoView({ block: "center" });
  } else if (target && scroll) {
    target.scrollIntoView();
  }
}

// --- the page text ---------------------------------------------------------------------------

function fillSiteText(catalog) {
  for (const node of $$("[data-site]")) node.textContent = SITE[node.dataset.site] ?? "";
  for (const node of $$("[data-needs]")) node.hidden = !SITE[node.dataset.needs];
  const links = Object.entries(SITE.links ?? {}).filter(([, url]) => url);
  for (const list of $$(".artist-links")) {
    list.replaceChildren(...links.map(([name, url]) =>
      el("li", {}, el("a", { class: "pill", href: url, target: "_blank", rel: "noopener" }, LINK_NAMES[name] ?? name))));
    list.hidden = links.length === 0;
  }
  for (const node of $$(".year")) node.textContent = new Date().getFullYear();
  for (const image of $$("img[data-logo]")) {
    const src = image.dataset.logo === "small" ? SITE.logoSmall || SITE.logo : SITE.logo;
    if (src) image.src = src;
  }
  const points = SITE.summary ?? [];
  $("#landing-points").replaceChildren(...points.map(({ title, text }) => el("li", {}, el("h3", {}, title), el("p", {}, text))));
  $("#landing-points").hidden = points.length === 0;
  if (catalog) {
    const total = catalog.tracks.reduce((sum, track) => sum + track.duration, 0);
    const songs = plural(catalog.tracks.length, "song");
    const albumCount = plural(catalog.albums.length, "album");
    $("#landing-stats").textContent = `${songs} · ${albumCount} · free to stream`;
    $("#music-stats").textContent = `${songs} · ${albumCount} · ${totalTime(total)}`;
  }
}

// Below the title screen: the releases, in the music page's order (newest first), each a link to
// its songs there.
function showReleases() {
  const released = [...albums.values()].filter((album) => album.release_date);
  $("#release-list").replaceChildren(...released.map((album) => {
    const seconds = album.tracks.reduce((sum, id) => sum + tracks.get(id).duration, 0);
    return el("li", {}, el("a", { class: "release", href: `#album-${album.id}` },
      el("span", { class: "release-cover" }, coverArt(album)),
      el("span", { class: "release-title" }, album.title),
      el("span", { class: "release-meta" }, `${releaseKind(album, album.tracks.length, seconds)} · ${album.year}`)));
  }));
  $("#releases").hidden = released.length === 0;
}

// --- the song list -----------------------------------------------------------------------------

// What a release is, the way the music stores count it: a single (up to three songs), an EP (up to
// six), both under half an hour, or else an album.
function releaseKind(album, songs, seconds) {
  if (!album.release_date) return "Unreleased";
  if (seconds < 30 * 60 && songs <= 3) return "Single";
  if (seconds < 30 * 60 && songs <= 6) return "EP";
  return "Album";
}

// An album: a heading (its cover, its name, what it is, when, and how long, and small buttons to
// play or shuffle it), then its songs.
function renderGroup(album) {
  const list = album.tracks.map((id) => tracks.get(id));
  const total = list.reduce((sum, track) => sum + track.duration, 0);
  const about = [releaseKind(album, list.length, total), album.year, plural(list.length, "song"), totalTime(total)];
  return el("section", { class: "group", id: `album-${album.id}`, dataset: { album: album.id }, "aria-labelledby": `album-title-${album.id}` },
    el("div", { class: "group-head" },
      el("div", { class: "group-cover", "aria-hidden": "true" }, coverArt(album)),
      el("div", { class: "group-text" },
        el("h3", { class: "group-title", id: `album-title-${album.id}` }, album.title),
        el("p", { class: "group-meta" }, about.filter(Boolean).join(" · "))),
      el("div", { class: "group-actions" },
        el("button", { class: "icon-button small", onclick: () => playAlbum(album, false), "aria-label": `Play ${album.title}`, title: "Play" }, icon("play")),
        el("button", { class: "icon-button small", onclick: () => playAlbum(album, true), "aria-label": `Shuffle ${album.title}`, title: "Shuffle" }, icon("shuffle")))),
    el("ol", { class: "tracklist" }, ...list.map((track, i) => renderTrack(track, i + 1, albumList(album)))));
}

// A song's row, numbered; clicking it plays `list` ({ids, label}) from it. In one list of all the
// songs, each row also names its album.
function renderTrack(track, number, list, withAlbum = false) {
  const album = albums.get(track.album);
  return el("li", {
    class: "track",
    id: `song-${track.id}`,
    dataset: { id: track.id, search: searchable(`${track.title} ${album.title}`) },
  },
    el("button", { class: "track-main", onclick: () => playFrom(list, track), title: `Play ${track.title}` },
      el("span", { class: "track-no", "aria-hidden": "true" },
        el("span", { class: "num" }, twoDigits(number)),
        el("span", { class: "eq" }, el("i"), el("i"), el("i")),
        icon("play")),
      el("span", { class: "track-title" }, track.title, withAlbum && el("span", { class: "track-album" }, album.title))),
    el("span", { class: "track-actions" },
      el("button", { class: "icon-button small", onclick: () => queueSong(track, "next"), "aria-label": `Play ${track.title} next`, title: "Play next" }, icon("play-next")),
      el("button", { class: "icon-button small", onclick: () => queueSong(track, "end"), "aria-label": `Add ${track.title} to the queue`, title: "Add to queue" }, icon("add"))),
    el("span", { class: "track-time" }, clock(track.duration)));
}

const albumList = (album) => ({ ids: album.tracks, label: album.title });

// Every song in the order chosen with the dropdown beside the search: by album, the way the page
// has always listed them (releases newest first, each in its own order); by popularity (site.js's
// ranking first, the rest after, in that order); by release date, newest first; or by title.
const SORT_LABELS = { albums: "all songs", popular: "Most popular", newest: "the newest songs", title: "all songs, A–Z" };
const byTitle = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });

function sortedSongs(order) {
  if (order === "popular") {
    const ranked = (SITE.popular ?? []).filter((id) => tracks.has(id));
    return [...ranked, ...allIds.filter((id) => !ranked.includes(id))];
  }
  if (order === "newest") {
    const released = (id) => albums.get(tracks.get(id).album).release_date ?? ""; // unreleased last
    return [...allIds].sort((a, b) => released(b).localeCompare(released(a))); // (a release keeps its order)
  }
  if (order === "title") return [...allIds].sort((a, b) => byTitle.compare(tracks.get(a).title, tracks.get(b).title));
  return allIds;
}

// The list: albums under their headings, or one list of all the songs, numbered in its order.
function renderSongs() {
  const order = sortSetting();
  if (order === "albums") {
    $("#albums").replaceChildren(...[...albums.values()].map(renderGroup));
  } else {
    const list = { ids: sortedSongs(order), label: SORT_LABELS[order] };
    $("#albums").replaceChildren(el("section", { class: "group all-songs", "aria-label": "Songs" },
      el("ol", { class: "tracklist" }, ...list.ids.map((id, i) => renderTrack(tracks.get(id), i + 1, list, true)))));
  }
  filterSongs();
  markCurrent();
}

// Songs and album headers slide in one after another (and the song in focus with them, when the
// page opens).
function animateList(withFocus = true) {
  if (graphics() === "off") return;
  let n = 0;
  for (const node of $$("#albums .group:not([hidden]) .group-head, #albums .track:not([hidden])")) {
    node.style.setProperty("--d", String(Math.min(n++, 20) * 30));
  }
  restart($("#song-list"), "enter");
  if (withFocus) restart($("#focus"), "enter");
}

// The search: only the songs that match it, under their albums.
function filterSongs() {
  const q = searchable($("#search").value.trim());
  let shown = 0;
  for (const group of $$(".group")) {
    let visible = 0;
    for (const row of group.querySelectorAll(".track")) {
      row.hidden = Boolean(q) && !row.dataset.search.includes(q);
      visible += !row.hidden;
    }
    group.hidden = visible === 0;
    shown += visible;
  }
  $("#no-results").hidden = shown > 0;
}

// --- the song in focus: the one playing (pointing at others in the list leaves it be) ----------

function defaultFocus() {
  return player.current?.id ?? allIds[0];
}

function setFocus(id) {
  if (!id || !tracks.has(id)) return;
  if (id !== focusId) {
    focusId = id;
    const track = tracks.get(id);
    const album = albums.get(track.album);
    const jacket = $("#focus-jacket");
    if (jacket.dataset.album !== album.id) {
      jacket.dataset.album = album.id;
      jacket.replaceChildren(coverArt(album));
      restart(jacket, "swap");
    }
    $("#focus-title").textContent = track.title;
    $("#focus-album").textContent = [album.title, album.year].filter(Boolean).join(" · ");
    $("#focus-meta").textContent = [clock(track.duration), track.bpm && `${track.bpm} BPM`, track.key].filter(Boolean).join(" · ");
    for (const node of [$("#focus-title"), $("#focus-album"), $("#focus-meta")]) restart(node, "focus-text-swap");
  }
  showFocusState();
}

function showFocusState() {
  const track = tracks?.get(focusId);
  if (!track) return;
  const isCurrent = player.current?.id === focusId;
  const playing = isCurrent && player.playing;
  const album = albums.get(track.album);
  const state = $("#focus-state");
  state.textContent = isCurrent
    ? (playing ? "Now playing" : "Paused")
    : album.tracks.length === 1 ? "Single" : `Track ${album.tracks.indexOf(track.id) + 1} of ${album.tracks.length}`;
  state.classList.toggle("playing", playing);
  setIcon($("#focus-play"), playing ? "pause" : "play");
  $("#focus-play span").textContent = playing ? "Pause" : "Play";
}

// --- choosing what plays ---------------------------------------------------------------------

function playAlbum(album, shuffle) {
  if (shuffle !== player.shuffle) player.setShuffle(shuffle);
  player.playList(album.tracks, { label: album.title });
}

// Every song, in the list's order.
function playEverything(shuffle) {
  if (shuffle !== player.shuffle) player.setShuffle(shuffle);
  const order = sortSetting();
  player.playList(sortedSongs(order), { label: SORT_LABELS[order] });
}

// A song, then the rest of its list ({ids, label}: its album, or the list in the chosen order).
function playFrom(list, track) {
  if (player.current?.id === track.id) {
    player.toggle(); // clicking the song that's playing pauses or resumes it
    return;
  }
  player.playList(list.ids, { start: track.id, label: list.label });
}

function queueSong(track, where) {
  if (where === "next") player.playNext(track.id);
  else player.addToQueue(track.id);
  toast(where === "next" ? `“${track.title}” will play next` : `Added “${track.title}” to the queue`);
}

function togglePlay() {
  if (player.current) player.toggle();
  else playEverything(player.shuffle);
}

// --- the player bar ----------------------------------------------------------------------------

let draggingSeek = false;

function showTrack() {
  const track = player.current;
  const album = track && albums.get(track.album);
  markCurrent();
  document.body.classList.toggle("has-track", Boolean(track));
  $("#now-title").textContent = track ? track.title : "Pick a song to start";
  $("#now-album").textContent = album ? album.title : "";
  const nowCover = $("#now-cover");
  if (nowCover.dataset.album !== (album?.id ?? "")) {
    nowCover.dataset.album = album?.id ?? "";
    nowCover.replaceChildren(...(album ? [coverArt(album)] : []));
  }
  for (const id of ["#now-cover", "#copy-link", "#seek", "#fullscreen", "#details-toggle"]) $(id).disabled = !track;
  // the song in focus on the music page catches up when the full-screen view closes
  if (!visualOpen()) setFocus(defaultFocus());
  if (visualOpen()) showVisual(false);
  showWave();
  preloadNext();
  if (track && panel === "details" && detailsFollow && detailsId !== track.id) {
    detailsId = track.id;
    showDetails();
  }
}

// The song playing is lit in the list.
function markCurrent() {
  for (const row of $$(".track.current")) row.classList.remove("current");
  if (player.current) document.getElementById(`song-${player.current.id}`)?.classList.add("current");
}

// The seek bar's wave: the outline of the song playing, from its analysis.
function showWave() {
  const track = player.current;
  const wave = $("#wave");
  wave.classList.remove("ready");
  loadAnalysis(track).then((data) => {
    if (!data?.wave || player.current?.id !== track.id) return;
    const paths = wavePaths(data.wave);
    for (const path of wave.querySelectorAll(".wave-shape")) path.setAttribute("d", paths.wave);
    for (const path of wave.querySelectorAll(".wave-reflection")) path.setAttribute("d", paths.reflection);
    wave.classList.add("ready");
  });
}

function showState() {
  const playing = player.playing;
  const track = player.current;
  document.body.classList.toggle("is-playing", playing);
  $("#player-bar").classList.toggle("buffering", player.buffering);
  const svg = $("#play svg");
  const name = playing ? "pause" : "play";
  if (svg.dataset.icon !== name) {
    svg.dataset.icon = name;
    setIcon($("#play"), name);
    replay(svg, "pop");
  }
  $("#play").setAttribute("aria-label", playing ? "Pause" : "Play");
  document.title = playing && track ? `${track.title} · ${SITE.artist}` : SITE.artist;
  showFocusState();
  // in full screen, pressing play or pause shows the controls (they stay while paused)
  if (playing !== wasPlaying) {
    wasPlaying = playing;
    if (visualOpen()) wake();
  }
}

function showTime() {
  const seek = $("#seek");
  const duration = player.duration;
  seek.max = duration || 1;
  if (!draggingSeek) {
    seek.value = player.time;
    $("#time-current").textContent = clock(player.time);
  }
  $("#time-total").textContent = clock(duration);
  $("#seek-wrap").style.setProperty("--fill", `${(Number(seek.value) / (duration || 1)) * 100}%`);
  if (panel === "details" && player.current?.id === detailsId) markMoment($("#details-body"), player.time);
}

function showModes() {
  const shuffle = $("#shuffle");
  shuffle.setAttribute("aria-pressed", String(player.shuffle));
  shuffle.title = `Shuffle: ${player.shuffle ? "on" : "off"} (S)`;
  const repeat = $("#repeat");
  repeat.dataset.mode = player.repeat;
  repeat.setAttribute("aria-pressed", String(player.repeat !== "off"));
  const label = { off: "off", all: "all songs", one: "this song" }[player.repeat];
  repeat.setAttribute("aria-label", `Repeat: ${label}`);
  repeat.title = `Repeat: ${label} (R)`;
}

function showVolume() {
  const { volume, muted } = player.audio;
  const slider = $("#volume");
  slider.value = muted ? 0 : volume;
  slider.style.setProperty("--fill", `${(muted ? 0 : volume) * 100}%`);
  setIcon($("#mute"), muted || volume === 0 ? "mute" : "volume");
  $("#mute").setAttribute("aria-label", muted ? "Unmute" : "Mute");
}

// --- the side panels: the queue, and a song's details ------------------------------------------

const PANELS = { queue: ["#queue-panel", "#queue-toggle"], details: ["#details-panel", "#details-toggle"] };

// Open one panel (closing the other), or close them with null.
function setPanel(name) {
  if (name === panel) return;
  panel = name;
  for (const [key, [box, toggle]] of Object.entries(PANELS)) {
    const open = key === name;
    $(box).classList.toggle("open", open);
    $(box).inert = !open;
    $(toggle).setAttribute("aria-expanded", String(open));
    $(toggle).classList.toggle("active", open);
  }
  if (!name) return;
  const box = $(PANELS[name][0]);
  if (name === "queue") showQueue();
  else showDetails();
  let n = 0;
  for (const row of box.querySelectorAll(name === "queue" ? ".queue-row" : ".side-body > *")) {
    row.style.setProperty("--d", String(Math.min(n++, 12) * 35));
  }
  restart(box, "entering");
  setTimeout(() => box.classList.remove("entering"), 1200);
  box.querySelector(".side-head button").focus({ preventScroll: true });
}

// --- the queue ---------------------------------------------------------------------------------

function queueRow(item, isCurrent) {
  const track = tracks.get(item.id);
  const album = albums.get(track.album);
  return el("li", { class: `queue-row${isCurrent ? " current" : ""}` },
    el("button", {
      class: "queue-main",
      onclick: isCurrent ? () => player.toggle() : () => player.jump(item.key),
      title: isCurrent ? "Play or pause" : `Play ${track.title} now`,
    },
      el("span", { class: "queue-cover", "aria-hidden": "true" }, coverArt(album)),
      el("span", { class: "queue-text" }, el("span", { class: "queue-title" }, track.title), el("span", { class: "queue-album" }, album.title))),
    el("span", { class: "track-time" }, clock(track.duration)),
    isCurrent ? null : el("button", { class: "icon-button small", onclick: () => player.remove(item.key), "aria-label": `Remove ${track.title} from the queue`, title: "Remove" }, icon("close")));
}

function showQueue() {
  const current = player.current;
  $("#queue-current").replaceChildren(...(current ? [queueRow({ id: current.id }, true)] : []));
  const upcoming = player.upcoming;
  const added = upcoming.filter((item) => item.added);
  const rest = upcoming.filter((item) => !item.added);
  $("#queue-added").replaceChildren(...added.map((item) => queueRow(item, false)));
  $("#queue-context").replaceChildren(...rest.map((item) => queueRow(item, false)));
  $("#queue-added-section").hidden = added.length === 0;
  $("#queue-context-section").hidden = rest.length === 0;
  const from = player.contextLabel ? `Next from ${player.contextLabel}` : "Next up";
  $("#queue-context-title").textContent = player.shuffle ? `${from} (shuffled)` : from;
  $("#queue-empty").hidden = upcoming.length > 0;
}

// --- a song's details: what the analysis found (details.js) ----------------------------------

function openDetails(id) {
  if (!tracks?.has(id)) return;
  detailsId = id;
  detailsFollow = id === player.current?.id;
  if (panel === "details") showDetails();
  else setPanel("details");
}

function toggleDetails(id) {
  if (panel === "details") setPanel(null);
  else openDetails(id);
}

function showDetails() {
  const track = tracks.get(detailsId);
  const album = albums.get(track.album);
  const body = $("#details-body");
  const draw = (data, note, message) => renderDetails(body, {
    track, album, data, note, message, cover: coverArt(album), onPlay: (seconds) => playMoment(track, seconds),
  });
  draw(null, null, track.analysis ? "Loading the analysis…" : "This song hasn't been analyzed yet.");
  Promise.all([loadAnalysis(track), loadNotes()]).then(([data, notes]) => {
    if (detailsId !== track.id || !track.analysis) return;
    if (!data) {
      draw(null, null, "The analysis couldn't be loaded. Please try again in a moment.");
      return;
    }
    draw(data, notes.get(track.id));
    body.scrollTop = 0;
    if (player.current?.id === track.id) markMoment(body, player.time);
  });
}

// Play a song from one of its moments.
function playMoment(track, seconds) {
  if (player.current?.id !== track.id) {
    const album = albums.get(track.album);
    player.playList(album.tracks, { start: track.id, label: album.title });
  }
  player.seek(seconds);
  if (!player.playing) player.play();
}

// --- the full-screen view ----------------------------------------------------------------------

let idleTimer;
let coverTimer;
let frames = null; // counts how smoothly the view runs, for Settings > Graphics' advice (js/device.js)
const visualOpen = () => $("#visual").classList.contains("open");

function showVisual(force) {
  const album = albums.get(player.current.album);
  const visual = $("#visual");
  // a new song while full screen is open: a soft swell of light (opening it unfolds the cover instead)
  if (!force && visual.dataset.track !== player.current.id) flashCover();
  visual.dataset.track = player.current.id;
  showPalette(album, !force);
  showCover(album, force);
}

// The album's colors are on two copies of the backdrop and of the glow behind the cover (style.css,
// .palette): a new album's colors go on the copy that isn't showing, which then fades in over the
// other. Opening the view just recolors the copy that shows; it's still fading in itself.
let palette = 0;
let paletteAlbum = null;

function showPalette(album, fade) {
  if (album.id === paletteAlbum) return;
  const first = paletteAlbum === null; // both copies get colors of their own, so neither follows the frame's
  paletteAlbum = album.id;
  if (fade) palette = 1 - palette;
  for (const [n, backdrop] of $$("#visual .backdrop").entries()) {
    if (n === palette || first) album.colors.forEach((color, i) => backdrop.style.setProperty(`--c-${i + 1}`, color));
  }
  for (const [n, glow] of $$("#visual .visual-glow i").entries()) {
    if (n === palette || first) glow.style.setProperty("--c-1", album.colors[0]);
  }
  const backdrop = $$("#visual .backdrop")[palette];
  const glow = $$("#visual .visual-glow i")[palette];
  for (const node of $$("#visual .palette")) node.classList.toggle("on", node === backdrop || node === glow);
  // the rest in the album's color (the cover's glow, the turning diamond, the flash) changes with the
  // cover, and so do the live EQ's bars
  album.colors.forEach((color, i) => $(".visual-frame").style.setProperty(`--c-${i + 1}`, color));
  $("#live-eq").style.setProperty("--album-color", album.colors[0]);
}

// Each album's full-screen cover, decoded ahead of time and kept, so a new cover never has to wait to
// be decoded while it unfolds, and is only swapped in once it's ready.
const largeCovers = new Map(); // album id -> { art, ready }

function largeCover(album) {
  if (!largeCovers.has(album.id)) {
    const art = coverArt(album, true);
    largeCovers.set(album.id, { art, ready: art.decode ? art.decode().catch(() => {}) : Promise.resolve() });
  }
  return largeCovers.get(album.id);
}

function showCover(album, force) {
  const cover = $("#visual-cover");
  if (!force && cover.dataset.album === album.id) return;
  cover.dataset.album = album.id;
  const { art, ready } = largeCover(album);
  ready.then(() => {
    if (cover.dataset.album !== album.id) return; // another album came along first
    cover.replaceChildren(art);
    unfoldCover();
  });
}

// The full-screen view's own animations are started from here rather than by putting classes on and
// off: a new one can start at any moment, even over one still running (it simply takes over), the
// page never has to be laid out to start one, and there's nothing left to tidy up after. With
// graphics Off there are none. (--ease-out in style.css is the same curve as EASE_OUT.)
const EASE_OUT = "cubic-bezier(0.2, 0.9, 0.25, 1)";

// The cover unfolds from a diamond. Its shadow and the faint diamond turning behind it wait until it
// has filled its square, then fade in: around the unfolding cover they framed the square's empty
// corners, a dark box. (Started this way, Chrome runs all of it on the graphics card: the picture
// isn't painted again for each frame of the unfolding.)
function unfoldCover() {
  if (graphics() === "off") return;
  $("#visual-cover").animate([
    { clipPath: "polygon(50% 50%, 50% 50%, 50% 50%, 50% 50%)", easing: EASE_OUT },
    { clipPath: "polygon(50% 0, 100% 50%, 50% 100%, 0 50%)", offset: 0.45, easing: EASE_OUT },
    { clipPath: "polygon(100% 0, 100% 100%, 0 100%, 0 0)" },
  ], { duration: 900 });
  // out of sight for 720 ms (the cover's corners are then within a few pixels of the square's), then a
  // soft fade; the turning diamond's last keyframe is left out, so it fades to what the music has set
  const wait = [{ opacity: 0 }, { opacity: 0, offset: 0.6, easing: "ease-in-out" }];
  $(".visual-art").animate([...wait, { opacity: 1 }], { duration: 1200, pseudoElement: "::before" });
  $(".visual-frame").animate(wait, { duration: 1200, pseudoElement: "::after" });
}

// A new song: a soft light in the album's color swells and fades over the cover, and a thin diamond
// drifts out from it.
function flashCover() {
  if (graphics() === "off") return;
  const flash = $("#visual-flash");
  flash.animate([
    { opacity: 0, easing: "ease-in-out" },
    { opacity: 1, offset: 0.35, easing: "ease-in-out" },
    { opacity: 0 },
  ], { duration: 1400 });
  const diamond = "translate(-50%, -50%) rotate(45deg)";
  const drift = "cubic-bezier(0.25, 0.6, 0.3, 1)";
  flash.animate([
    { opacity: 0, transform: `${diamond} scale(0.8)`, easing: drift },
    { opacity: 0.6, offset: 0.25, easing: drift },
    { opacity: 0, transform: `${diamond} scale(1.8)` },
  ], { duration: 1100, pseudoElement: "::after" });
}

// While a song plays, the next ones get ready in idle moments: their analysis (the backgrounds, the
// wave, the effects all read it) and, in full screen, their covers. Skipping ahead then finds them
// loaded.
const idle = (fn) => (window.requestIdleCallback ? requestIdleCallback(fn, { timeout: 3000 }) : setTimeout(fn, 300));

function preloadNext() {
  const next = player.upcoming.slice(0, 2).map((entry) => tracks.get(entry.id)).filter(Boolean);
  idle(() => {
    for (const track of next) {
      loadAnalysis(track);
      if (visualOpen()) largeCover(albums.get(track.album));
    }
  });
}

// While the music plays and nothing moves, the pointer, the exit button, and the player bar get out
// of the way, like a video player's controls; moving the pointer, a tap, or a key brings them back.
function wake() {
  $("#visual").classList.remove("idle");
  document.body.classList.remove("controls-hidden");
  clearTimeout(idleTimer);
  if (visualOpen() && player.playing) idleTimer = setTimeout(rest, IDLE_MS);
}

function rest() {
  const bar = $("#player-bar");
  const usingBar = bar.matches(":hover") || (document.documentElement.dataset.input === "keyboard" && bar.contains(document.activeElement));
  if (usingBar || panel) {
    idleTimer = setTimeout(rest, IDLE_MS);
    return;
  }
  $("#visual").classList.add("idle");
  document.body.classList.add("controls-hidden");
}

function setVisualOpen(open) {
  if ((open && !player.current) || open === visualOpen()) return;
  const visual = $("#visual");
  visual.classList.toggle("open", open);
  visual.setAttribute("aria-hidden", String(!open));
  document.body.classList.toggle("visual-open", open);
  $("#fullscreen").setAttribute("aria-pressed", String(open));
  $("#fullscreen").setAttribute("aria-label", open ? "Exit full screen" : "Full screen");
  setIcon($("#fullscreen"), open ? "collapse" : "expand");
  clearTimeout(coverTimer);
  frames?.check();
  if (open) {
    showVisual(true);
    preloadNext();
    wake();
    // once the view has faded in over everything, the page under it isn't drawn (style.css)
    coverTimer = setTimeout(() => visualOpen() && document.body.classList.add("visual-covered"), 500);
    // true full screen where the browser allows it (iPhones only allow it for videos)
    if (document.fullscreenEnabled && !document.fullscreenElement) {
      document.documentElement.requestFullscreen({ navigationUI: "hide" }).catch(() => {});
    }
  } else {
    document.body.classList.remove("visual-covered");
    setFocus(defaultFocus());
    clearTimeout(idleTimer);
    visual.classList.remove("idle");
    document.body.classList.remove("controls-hidden");
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }
}

// --- wiring ------------------------------------------------------------------------------------

function wireControls() {
  // the songs' order: the dropdown beside the search
  const sort = dropdown($("#sort-choice"), setSort);
  sort.show(sortSetting());
  onSettingsChange((what) => {
    if (what !== "sort") return;
    sort.show(sortSetting());
    renderSongs();
    animateList(false);
  });
  $("#play-all").addEventListener("click", () => playEverything(false));
  $("#shuffle-all").addEventListener("click", () => playEverything(true));
  $("#play").addEventListener("click", togglePlay);
  $("#next").addEventListener("click", () => player.next());
  $("#prev").addEventListener("click", () => player.previous());
  $("#shuffle").addEventListener("click", () => {
    player.setShuffle(!player.shuffle);
    toast(player.shuffle ? "Shuffle on" : "Shuffle off");
  });
  $("#repeat").addEventListener("click", () => {
    player.cycleRepeat();
    toast({ off: "Repeat off", all: "Repeating all songs", one: "Repeating this song" }[player.repeat]);
  });

  const seek = $("#seek");
  seek.addEventListener("input", () => {
    draggingSeek = true;
    $("#time-current").textContent = clock(seek.value);
    $("#seek-wrap").style.setProperty("--fill", `${(seek.value / (seek.max || 1)) * 100}%`);
  });
  seek.addEventListener("change", () => {
    draggingSeek = false;
    player.seek(Number(seek.value));
  });
  // pointing along the seek bar shows the time there
  const tip = $("#seek-tip");
  $("#seek-wrap").addEventListener("pointermove", (event) => {
    if (!player.current || event.pointerType === "touch") return;
    const box = event.currentTarget.getBoundingClientRect();
    const x = Math.min(Math.max(event.clientX - box.left, 0), box.width);
    tip.textContent = clock((x / box.width) * player.duration);
    tip.style.left = `${x}px`;
    tip.hidden = false;
  });
  $("#seek-wrap").addEventListener("pointerleave", () => {
    tip.hidden = true;
  });

  const volume = $("#volume");
  volume.addEventListener("input", () => player.setVolume(Number(volume.value)));
  $("#mute").addEventListener("click", () => player.toggleMute());
  // Phones (iPhone especially) only allow the hardware volume buttons.
  const probe = new Audio();
  probe.volume = 0.5;
  if (probe.volume !== 0.5) $("#volume-group").hidden = true;

  $("#queue-toggle").addEventListener("click", () => setPanel(panel === "queue" ? null : "queue"));
  $("#queue-close").addEventListener("click", () => setPanel(null));
  $("#details-toggle").addEventListener("click", () => toggleDetails(player.current?.id));
  $("#details-close").addEventListener("click", () => setPanel(null));
  $("#clear-added").addEventListener("click", () => player.clearUpcoming("added"));
  $("#clear-context").addEventListener("click", () => player.clearUpcoming("context"));

  $("#fullscreen").addEventListener("click", () => setVisualOpen(!visualOpen()));
  $("#now-cover").addEventListener("click", () => setVisualOpen(true));
  $("#visual-exit").addEventListener("click", () => setVisualOpen(false));
  $("#visual").addEventListener("dblclick", () => setVisualOpen(false));
  for (const name of ["pointermove", "pointerdown"]) document.addEventListener(name, () => visualOpen() && wake());
  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement) setVisualOpen(false); // Esc, or the browser's own exit
  });

  $("#focus-play").addEventListener("click", () => {
    const track = tracks.get(focusId);
    playFrom(albumList(albums.get(track.album)), track);
  });
  $("#focus-next").addEventListener("click", () => queueSong(tracks.get(focusId), "next"));
  $("#focus-add").addEventListener("click", () => queueSong(tracks.get(focusId), "end"));
  $("#focus-details").addEventListener("click", () => openDetails(focusId));

  $("#copy-link").addEventListener("click", async () => {
    const track = player.current;
    const url = `${location.origin}${location.pathname}#song-${track.id}`;
    try {
      await navigator.clipboard.writeText(url);
      toast("Link copied");
    } catch {
      toast(url);
    }
  });

  $("#search").addEventListener("input", filterSongs);

  document.addEventListener("keydown", onKey);
  // Space plays or pauses (on keydown); it must not also press the button that has focus
  document.addEventListener("keyup", (event) => {
    if (event.key === " " && event.target.closest?.("button, input[type=checkbox]")) event.preventDefault();
  });
  // The focus outline is for moving around with the keyboard: it shows once Tab is pressed, and a
  // click hides it again, so clicking a button never leaves a box around it.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Tab") document.documentElement.dataset.input = "keyboard";
  }, true);
  document.addEventListener("pointerdown", () => {
    document.documentElement.dataset.input = "pointer";
  }, true);

  player.addEventListener("change", ({ detail }) => {
    if (detail === "track") showTrack();
    if (detail === "volume") showVolume();
    if (detail === "error" && player.failed) toast(`Couldn't load “${player.failed.title}”. Check your connection and try again.`);
    if (["track", "time"].includes(detail)) showTime();
    if (["track", "state", "error"].includes(detail)) showState();
    if (["track", "queue", "mode"].includes(detail)) {
      showModes();
      if (panel === "queue") showQueue();
    }
  });
}

function onKey(event) {
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
  const target = event.target;
  const field = target.closest?.("input, textarea, select, [contenteditable]");
  if (field && field.type !== "range" && field.type !== "checkbox") return; // typing in the search box
  const onButton = target.closest?.("button, a, input");
  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
  if (visualOpen()) wake();
  const home = document.body.dataset.view === "home";
  const actions = {
    " ": togglePlay, // always, even when a button has focus (it isn't pressed again)
    k: togglePlay,
    ArrowRight: () => target.id !== "volume" && player.seekBy(SEEK_STEP_S),
    ArrowLeft: () => target.id !== "volume" && player.seekBy(-SEEK_STEP_S),
    n: () => player.next(),
    p: () => player.previous(),
    s: () => $("#shuffle").click(),
    r: () => $("#repeat").click(),
    m: () => player.toggleMute(),
    q: () => setPanel(panel === "queue" ? null : "queue"),
    d: () => toggleDetails(player.current?.id ?? focusId),
    f: () => setVisualOpen(!visualOpen()),
    // Enter switches a focused checkbox (Space plays and pauses), and starts on the landing page
    Enter: () => (target.type === "checkbox" ? target.click() : home && !onButton && (location.hash = "music")),
    Escape: () => {
      if (panel) setPanel(null);
      else if (visualOpen()) setVisualOpen(false);
      else if (document.body.dataset.view === "settings") location.hash = backTo;
      else return false;
    },
  };
  const action = actions[key];
  if (!action) return;
  if (action() !== false) event.preventDefault();
}

async function main() {
  showTheme();
  fillSiteText(null);
  wireSettings();
  prefersLight.addEventListener("change", showTheme);
  showView(true);
  window.addEventListener("hashchange", () => showView(false));
  // what this device is, for Settings > Graphics' advice: once, while nothing else is going on
  idle(() => {
    aboutDevice();
    deviceKnown = true;
    showSettings();
  });
  let catalog;
  try {
    const response = await fetch(CATALOG_URL, { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    catalog = await response.json();
  } catch (error) {
    $("#library-status").textContent = "The music couldn't be loaded. Please try again in a moment.";
    console.error("Couldn't load library/catalog.json (run python scripts/build_catalog.py):", error);
    return;
  }
  // paths in the catalog are relative to the catalog itself
  const resolve = (path) => path && new URL(path, CATALOG_URL).href;
  for (const album of catalog.albums) {
    album.cover = resolve(album.cover);
    album.cover_large = resolve(album.cover_large);
  }
  for (const track of catalog.tracks) {
    track.src = resolve(track.src);
    track.analysis = resolve(track.analysis);
  }

  albums = new Map(catalog.albums.map((album) => [album.id, album]));
  tracks = new Map(catalog.tracks.map((track) => [track.id, track]));
  allIds = catalog.albums.flatMap((album) => album.tracks);
  player = new Player({ tracks: catalog.tracks, albums: catalog.albums, artist: SITE.artist });
  if (new URLSearchParams(location.search).has("debug")) window.synopsistPlayer = player; // for testing
  // the light goes only to what uses it, while it's shown: the moonlight behind the pages, and the
  // full-screen view
  const pageShown = () => !document.body.classList.contains("visual-covered");
  followTheMusic(player, [
    [$(".scenery .sky"), pageShown],
    ...["#visual .backdrops", "#visual .visual-frame", "#visual .scenes"].map((selector) => [$(selector), visualOpen]),
  ]);
  songEffects(player, { page: $("#page-effects"), back: $("#visual-effects"), front: $("#visual-front") });
  frames = countFrames(player, visualOpen);
  const eq = equalize(player); // before the live EQ, which reads it
  liveEq($("#live-eq"), player, eq, visualOpen);
  if (new URLSearchParams(location.search).has("debug")) window.synopsistEq = eq; // for testing

  fillSiteText(catalog);
  renderSongs();
  showReleases();
  $("#library-status").hidden = true;
  wireControls();
  filterSongs(); // a search the browser kept from before
  showTrack();
  showState();
  showTime();
  showModes();
  showVolume();
  // the bar's height (it wraps on phones) keeps the pages, queue, and messages clear of it
  new ResizeObserver(() => document.documentElement.style.setProperty("--bar-h", `${$("#player-bar").offsetHeight}px`))
    .observe($("#player-bar"));
  showView(true); // again, now that a link to a song can load it
  if (document.body.dataset.view === "player") animateList();
}

main();
