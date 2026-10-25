// The seek bar's wave: the outline of a song's loudness from start to end (from its published
// analysis), drawn as a shape rising from the seek line with a fainter reflection under it. The
// SVGs in the player bar use a 1000 x 100 viewBox stretched to the bar, with the line 60% of the way
// down (style.css: .seek). When there's listening data, the same shape can show where listeners
// replay the most.

const WIDTH = 1000;
const LINE = 60;
const RISE = 57; // the tallest wave above the line,
const DIP = 26; // and its reflection below it

function outline(values, height) {
  const step = WIDTH / values.length;
  const points = values.map((value, i) => `${((i + 0.5) * step).toFixed(1)},${(LINE - (value / 100) * height).toFixed(1)}`);
  return `M0,${LINE}L${points.join("L")}L${WIDTH},${LINE}Z`;
}

// Path data for the wave above the line and for its reflection.
export function wavePaths(values) {
  return { wave: outline(values, RISE), reflection: outline(values, -DIP) };
}
