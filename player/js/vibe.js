// The backgrounds follow the music. Each song's analysis (analysis.js) has a curve for its bass,
// mids, and highs: how strong each is at every moment, already averaged over a few seconds so drum
// hits don't make the light pulse. While a song plays, the curves are read at the playback
// position, eased, and handed to CSS as --bass, --mids, and --highs (0 to 1) on the backdrops: the
// bass sets how brightly they shine overall, and each band lights its own part of the gradient.
// Nothing listens to the audio itself, so it costs almost nothing and keeps working with the
// screen locked.
//
// The light changes slowly, so it's handed over at most 20 times a second (10 on Low graphics), and
// only to the backdrops on screen: each change restyles a backdrop and redraws the screen, so fewer
// of them is most of what keeps playback light. In full screen, style.css glides from one value to
// the next (--vibe-step), so the outline behind the cover doesn't move in steps. A backdrop that
// comes into view (the full-screen view opening, a change of page) gets the current values before
// it's first drawn. With graphics Off the backgrounds hold still.

import { loadAnalysis } from "./analysis.js";
import { graphics, onSettingsChange } from "./settings.js";

const BANDS = ["bass", "mids", "highs"];
const REST = 0.35; // every band, when nothing is playing
const RISE_S = 0.5; // how quickly the light follows a band getting stronger,
const FALL_S = 1.1; // and how slowly it settles when the band fades
const EVERY_MS = { high: 50, low: 100 }; // how often the backdrops get new values
const STEP = 0.01; // and only when a value has changed by at least this much

// targets: [node, isShown] for each backdrop; isShown() says whether it's on screen, from the page's
// state (asking the browser instead would make it work out the page's styles every time)
export function followTheMusic(player, targets) {
  const level = Object.fromEntries(BANDS.map((band) => [band, REST]));
  const shown = new Map(targets.map(([node]) => [node, {}])); // what each backdrop shows now
  const isShown = new Map(targets);
  let curves = null;
  let frame = 0;
  let last = 0;
  let handed = -Infinity; // when the backdrops last got new values

  function load(track) {
    curves = null;
    loadAnalysis(track).then((data) => {
      if (data && player.current?.id === track.id) curves = data;
    });
  }

  // A curve's value at a time, between its points.
  function at(values, time) {
    if (!values?.length) return REST;
    const x = time / curves.hop - 0.5;
    if (x <= 0) return values[0] / 100;
    const i = Math.min(Math.floor(x), values.length - 1);
    const next = values[Math.min(i + 1, values.length - 1)];
    return (values[i] + (next - values[i]) * (x - i)) / 100;
  }

  // Only to backdrops that are drawn (the landing page's isn't while the music page shows, nor the
  // full-screen view's while it's closed); each gets the current values when it shows again. `force`
  // skips the small-change threshold; `everywhere` reaches hidden backdrops too.
  function hand(force, everywhere = false) {
    for (const [node, values] of shown) {
      if (!everywhere && !isShown.get(node)()) continue;
      for (const band of BANDS) {
        const shownValue = values[band] ?? -1;
        if (shownValue === level[band] || (!force && Math.abs(level[band] - shownValue) < STEP)) continue;
        values[band] = level[band];
        node.style.setProperty(`--${band}`, level[band].toFixed(2));
      }
    }
  }

  function tick(now) {
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    const mode = graphics();
    const live = player.playing && curves && mode !== "off";
    let settling = false;
    for (const band of BANDS) {
      const target = live ? at(curves[band], player.time) : REST;
      level[band] += (target - level[band]) * (1 - Math.exp(-dt / (target > level[band] ? RISE_S : FALL_S)));
      if (Math.abs(target - level[band]) > 0.003) settling = true;
      else if (!live) level[band] = REST;
    }
    // keep going while playing; once paused, stop as soon as the backgrounds have settled, and give
    // every backdrop, shown or not, the resting values
    if (live || settling) {
      frame = requestAnimationFrame(tick);
      if (now - handed >= (EVERY_MS[mode] ?? EVERY_MS.high)) {
        handed = now;
        hand(false);
      }
    } else {
      frame = 0;
      hand(true, true);
    }
  }

  function wake() {
    if (frame) return;
    last = performance.now();
    frame = requestAnimationFrame(tick);
  }

  hand(true, true);
  // a backdrop that comes into view (its own class changes, or something around it: the full-screen
  // view opening, a change of page) gets the current values before it's drawn, not the ones it had
  // when it was last on screen
  const appearing = new MutationObserver((changes) => {
    if (changes.some(({ target }) => targets.some(([node]) => target.contains(node)))) hand(true);
  });
  appearing.observe(document.body, { attributes: true, attributeFilter: ["class", "data-view"], subtree: true });
  player.addEventListener("change", ({ detail }) => {
    if (detail === "track") load(player.current);
    if (detail === "track" || detail === "state") wake();
  });
  onSettingsChange((what) => what === "graphics" && wake());
  load(player.current);
}
