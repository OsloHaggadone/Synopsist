// The effects for the songs listed here: glowing particles and rays of light while the song plays,
// behind the page and in the full-screen view, and in full screen the song's own background light
// (its scene), each song with its own look, and a change when its chorus lands. Songs are listed by
// their track id from data/catalog.csv. Change the numbers and refresh the page to see the
// difference; there's nothing to rebuild. js/effects.js draws them.
//
// In full screen it's all in layers: the scene at the back, most particles behind the cover, then
// the rays and the nearest particles in front of it, and over everything a slight vignette, which
// every song has and which these songs' choruses lift.
//
// particles   count      how many on a full-HD screen (fewer on smaller screens)
//             size       their radius in pixels, [smallest, largest]
//             colors     picked at random for each particle ("#rrggbb")
//             shape      "dot" (a soft glow), "spark" (a bright point with a glow), "shard" (a small
//                        glass diamond that turns), or "petal" (a soft oval that tumbles)
//             flow       "drift" (all move by `drift`) or "out" (from the middle of the screen
//                        outward, faster the further out, like flying forward through them)
//             drift      [across, down] in pixels a second (negative: left, up)
//             speed      for "out": how fast they leave the middle, in pixels a second
//             spread     how much each particle's speed differs from the rest, in pixels a second
//             sway       how far each one wanders from its path, in pixels
//             twinkle    0 to 1: how much they shimmer
//             opacity    0 to 1
//             life       how long each one lasts before it fades and another appears, [shortest,
//                        longest] in seconds
//             depth      0 to 1: how much bigger, faster, and brighter the near ones are than the far ones
//             stretch    0 or more: drawn as streaks, longer the faster they move
//             spin       for shards and petals: turns a second, at most
//             front      0 to 1: the share of them in front of the cover in full screen (bigger,
//                        faster, out of focus); 0.15 if not given
// rays        from       where the light comes from, [across, down] as fractions of the screen
//                        (0 to 1; below 0 or above 1 is off screen)
//             angle      where it shines, in degrees: 0 to the right, 90 down, 180 left, 270 up
//             spread     degrees between the first ray and the last
//             count, width (pixels), length (a fraction of the screen's diagonal), color, opacity
// scene       the song's background light in full screen, in place of the album's moving glows: a
//             list of lights, each one
//               { light: "glow", at: [across, down], size: [width, height], ... }  an oval of light
//               { light: "band", at: [across, down], angle, width, ... }           a soft stripe of
//                 light through `at`, running at `angle` (degrees: 0 across, 90 down), `width`
//                 thick (a fraction of the screen's height)
//             with color, opacity, and chorus (its opacity while the chorus plays). Places and sizes
//             are fractions of the screen, with the cover in the middle (it covers about the middle
//             three quarters of the screen's height); the lights brighten with the bass.
// chorus      what changes while the chorus plays (it builds up over the few seconds before the drop
//             and is complete on it):
//             count, speed, opacity, size  multiply the particles' own
//             drift, stretch, colors       replace them
//             rays                         the rays' opacity
//             burst                        particles that appear into the drop: {count, from:
//                                          "center" or "everywhere", speed (pixels a second, for "center")}
//             swirl                        the particles circle around the middle of the screen (the
//                                          cover) at about this many pixels a second, the inner ones
//                                          a little faster, coming in with the chorus
// chorusTimes when the chorus plays, as ["m:ss-m:ss", ...]: only to correct the times found in the
//             song's analysis (src/synopsist/structure.py), which are used otherwise. A chorus can
//             also be {at: "m:ss-m:ss", size, breakBeats}: size 1 is as written, more for a bigger
//             one (1.25: everything the chorus changes, a quarter more); breakBeats when the music
//             drops out for that many beats right before it lands: the light goes dark at once, then
//             brightens back up into the drop
// bpm         the song's tempo, only to correct the one in its analysis (the catalog shows it). The
//             chorus comes in on the song's own time: it builds up over the last whole measures
//             before the drop (1, 2, 4, or 8, whichever comes closest to about 4 seconds at this
//             tempo, so a slow song takes fewer and a fast one more), and eases back over measures
//             after (js/effects.js, BUILD and the lines after it)
// buildMeasures how many measures the chorus builds up over, when the song wants its own
// beatsPerBar how many beats make a measure: 4 unless the song counts in 3 (a waltz) or 6
//
// A song can also take another song's look: "song-id": "other-song-id" (its chorus stays its own).

// How bright all of it is at once: 1 is as written below; lower is subtler, higher is brighter.
export const BRIGHTNESS = {
  particles: 0.4, // every song's particles
  light: 0.8, // every song's rays and scene lights
};

export const SONG_EFFECTS = {
  // Hollow Journey: moonlight over a dark city, blue-white

  // the title screen's music: sad and quiet, then surging with nostalgia. A few specks of moon dust
  // rising slowly, like the dust around the astronaut, under a cold sky lit by the cover's moon; when
  // the chorus lands, more of them, swirling around the cover as if remembering, and broad shafts of
  // moonlight falling over it
  "hollow-journey": {
    particles: { count: 55, size: [1.3, 3.2], colors: ["#e8f4ff", "#9fd8ff", "#7cc6d0"], shape: "spark",
      drift: [0, -9], spread: 5, sway: 10, twinkle: 0.5, opacity: 0.85, life: [10, 18], depth: 0.6 },
    rays: { from: [0.5, -0.25], angle: 90, spread: 36, count: 4, width: 260, length: 1.25, color: "#bfe6ff", opacity: 0 },
    scene: [
      { light: "glow", at: [0.5, -0.1], size: [1.5, 0.7], color: "#24506a", opacity: 0.5, chorus: 0.65 }, // a cold sky
      { light: "glow", at: [0.5, 0.3], size: [0.75, 0.6], color: "#9fd0ff", opacity: 0.22, chorus: 0.55 }, // the moon's light, behind the cover's moon
      { light: "band", at: [0.5, 0.85], angle: 0, width: 0.35, color: "#14303a", opacity: 0.55, chorus: 0.6 }, // haze over the city
    ],
    chorus: { count: 2.2, speed: 1.7, opacity: 1.45, rays: 0.2, swirl: 50, burst: { count: 20, from: "everywhere" } },
    chorusTimes: ["0:48-1:13"],
  },

  // a calm, steady drift outward through dark space past two faint nebulas: soft motes spread far
  // apart, floating; when the chorus lands they stream out from the middle, as if heading into space,
  // and the light ahead grows
  "into-space": {
    particles: { count: 40, size: [2.5, 7], colors: ["#cfe8ff", "#8fb8ff", "#b9a6ff"], shape: "dot",
      flow: "out", speed: 7, spread: 3, sway: 14, twinkle: 0.3, opacity: 0.7, life: [14, 24], depth: 0.8, front: 0.2 },
    scene: [
      { light: "glow", at: [0.18, 0.25], size: [0.6, 0.55], color: "#2c4796", opacity: 0.4, chorus: 0.5 },
      { light: "glow", at: [0.84, 0.78], size: [0.55, 0.5], color: "#56389a", opacity: 0.32, chorus: 0.45 },
      { light: "glow", at: [0.5, 0.5], size: [0.5, 0.5], color: "#a8c0ff", opacity: 0.06, chorus: 0.4 }, // ahead
    ],
    chorus: { count: 2.4, speed: 7, opacity: 1.4, stretch: 0.035, burst: { count: 24, from: "center", speed: 110 } },
    chorusTimes: ["1:43-2:28"],
  },

  // a long, unhurried, dreamy drift: big soft lights at different depths with plenty of room between
  // them, in pastel haze, a little dim between the choruses; the chorus comes in slowly, over four
  // measures, the same way both times, and slow rays of light reach in from the top left, over the
  // cover
  "spacial-awareness": {
    particles: { count: 18, size: [6, 24], colors: ["#7fd6e0", "#b7a3ff", "#f0b8ff"], shape: "dot",
      drift: [7, -2], spread: 4, sway: 14, twinkle: 0.15, opacity: 0.23, life: [18, 30], depth: 1, front: 0.2 },
    rays: { from: [-0.1, -0.2], angle: 38, spread: 26, count: 4, width: 170, length: 1.5, color: "#c9b8ff", opacity: 0 },
    scene: [
      { light: "glow", at: [0.12, 0.22], size: [0.6, 0.6], color: "#3f9fb0", opacity: 0.3, chorus: 0.45 },
      { light: "glow", at: [0.88, 0.32], size: [0.55, 0.55], color: "#7a62c8", opacity: 0.27, chorus: 0.42 },
      { light: "glow", at: [0.62, 0.95], size: [0.7, 0.5], color: "#b0609e", opacity: 0.19, chorus: 0.32 },
      { light: "glow", at: [0, 0], size: [0.8, 0.8], color: "#c8b8ff", opacity: 0.04, chorus: 0.4 }, // where the rays come from
    ],
    chorus: { count: 1.8, speed: 1.5, opacity: 2, rays: 0.17, burst: { count: 8, from: "everywhere" } },
    chorusTimes: ["2:24-2:48", "3:36-4:27"],
    buildMeasures: 4,
  },

  // Hollow Journey Beyond: a cave, mint light falling through it, a warm lantern

  // deep and dark, and driving: dark green dust streaming sideways through the depths of the cave,
  // with no light falling in, only a faint glow far off; when the chorus lands the dust speeds up into
  // streaks and the depths glow a little, but it stays dark
  "journey": {
    particles: { count: 80, size: [1.3, 3.2], colors: ["#5f9e80", "#8fcfae", "#3f7a60"], shape: "dot",
      drift: [55, -10], spread: 16, sway: 6, twinkle: 0.2, opacity: 0.6, life: [6, 12], depth: 0.9, stretch: 0.012 },
    scene: [
      { light: "glow", at: [0.5, 0.55], size: [1.2, 0.85], color: "#123a2b", opacity: 0.45, chorus: 0.62 }, // the depths
      { light: "glow", at: [0.84, 0.12], size: [0.45, 0.45], color: "#2c6a50", opacity: 0.1, chorus: 0.22 }, // far off
      { light: "glow", at: [0.25, 1.05], size: [0.9, 0.5], color: "#0f2a20", opacity: 0.5, chorus: 0.55 }, // the cave floor
    ],
    chorus: { count: 1.9, speed: 3, opacity: 1.45, stretch: 0.035, colors: ["#a8e6c4", "#6fbf96"],
      burst: { count: 20, from: "everywhere" } },
  },

  // warm and easygoing: soft petals and pollen drifting down and across, tumbling lazily, under warm
  // sun from the top left; in the fuller chorus, rays of sun over the cover and more petals
  "flowers-about": {
    particles: { count: 34, size: [6.5, 12], colors: ["#ffd98a", "#ffb8a0", "#b9f0c8"], shape: "petal",
      drift: [10, 14], spread: 6, sway: 20, twinkle: 0.1, opacity: 0.6, life: [12, 20], depth: 0.7, spin: 0.25 },
    rays: { from: [0.2, -0.3], angle: 68, spread: 24, count: 4, width: 190, length: 1.5, color: "#ffe2a8", opacity: 0 },
    scene: [
      { light: "glow", at: [0.15, -0.05], size: [0.8, 0.7], color: "#ffc27a", opacity: 0.22, chorus: 0.48 }, // the sun
      { light: "glow", at: [0.85, 0.95], size: [0.7, 0.55], color: "#3f8f5c", opacity: 0.38, chorus: 0.45 }, // green below
      { light: "glow", at: [0.92, 0.18], size: [0.45, 0.4], color: "#ff9a86", opacity: 0.12, chorus: 0.26 },
    ],
    chorus: { count: 2.2, speed: 1.4, opacity: 1.45, rays: 0.22, burst: { count: 14, from: "everywhere" } },
  },

  // the album's hit, in the cover's own light: the mouth of the cave full of pale green fog, a shaft
  // of light falling into it from the top right, the warm lantern low on the left, and dust hanging
  // in the light, drifting down. The chorus comes in over four measures: the fog brightens, the shaft
  // shines over the cover, and the dust thickens and rises.
  "facades": {
    particles: { count: 42, size: [1.2, 3.4], colors: ["#d6f0e0", "#9fc8b0", "#eef8f2"], shape: "spark",
      drift: [-3, 6], spread: 3, sway: 10, twinkle: 0.35, opacity: 0.7, life: [8, 14], depth: 0.6 },
    rays: { from: [0.72, -0.25], angle: 104, spread: 10, count: 3, width: 240, length: 1.5, color: "#d8f5e4", opacity: 0.05 },
    scene: [
      { light: "glow", at: [0.5, 0.46], size: [1.6, 1.3], color: "#5f8a72", opacity: 0.45, chorus: 0.85 }, // the cave's fog
      { light: "glow", at: [0.76, 0], size: [0.7, 0.6], color: "#cfeedd", opacity: 0.16, chorus: 0.5 }, // where the light falls in
      { light: "glow", at: [0.2, 0.86], size: [0.3, 0.25], color: "#ffcf7a", opacity: 0.16, chorus: 0.3 }, // the lantern
    ],
    chorus: { count: 2.2, speed: 2.2, opacity: 1.5, drift: [-4, -9], rays: 0.26, burst: { count: 22, from: "everywhere" } },
    chorusTimes: ["1:24.0-1:49.6", "3:04.8-3:56.4"], // each landing on the beat it hits
    buildMeasures: 4,
  },

  // Singles

  // moody and heavy: deep in the dark red tunnel on the cover, its far end glowing behind the cover,
  // embers drifting out of it; when the chorus lands they rush at you as streaks, hotter and brighter,
  // some past the cover, and the tunnel lights up
  "eternal-synopsis": {
    particles: { count: 55, size: [1.3, 3.6], colors: ["#ff6a2a", "#ff2929", "#ffb36b"], shape: "spark",
      flow: "out", speed: 16, spread: 4, sway: 6, twinkle: 0.6, opacity: 0.75, life: [5, 10], depth: 0.6, front: 0.2 },
    scene: [
      { light: "glow", at: [0.5, 0.5], size: [1.6, 1.6], color: "#3a0c08", opacity: 0.7, chorus: 0.85 }, // the tunnel
      { light: "glow", at: [0.5, 0.5], size: [0.8, 0.8], color: "#ff4a1a", opacity: 0.2, chorus: 0.5 }, // its far end
      { light: "glow", at: [0.5, 1.02], size: [1.3, 0.3], color: "#ff5a2a", opacity: 0.12, chorus: 0.35 }, // the floor
      { light: "glow", at: [0.5, -0.02], size: [1.3, 0.3], color: "#ff5a2a", opacity: 0.08, chorus: 0.26 }, // the ceiling
    ],
    chorus: { count: 2.4, speed: 5, opacity: 1.55, stretch: 0.045, colors: ["#ffd0a0", "#ff7a3a", "#ff3b2a"],
      burst: { count: 32, from: "center", speed: 200 } },
    chorusTimes: ["0:29.26-0:48.9", "1:40.36-2:05.2"],
  },

  // calm and hopeful: a misty sky over a pale field, the horizon running out from the cover's, pale
  // flecks drifting slowly down; in the chorus they turn and rise, the horizon and the sun behind
  // the cover glow, and the sun's rays reach up over the cover
  "planetary-fields-final-ver": {
    particles: { count: 45, size: [1.6, 4.2], colors: ["#e8fbff", "#a8e6ee", "#7cc0cc"], shape: "dot",
      drift: [5, 9], spread: 4, sway: 14, twinkle: 0.3, opacity: 0.65, life: [12, 20], depth: 0.7 },
    rays: { from: [0.5, 0.46], angle: 270, spread: 120, count: 6, width: 80, length: 0.85, color: "#d8fbff", opacity: 0 },
    scene: [
      { light: "glow", at: [0.5, -0.15], size: [1.5, 0.8], color: "#1f4d58", opacity: 0.55, chorus: 0.62 }, // the sky
      { light: "band", at: [0.5, 0.5], angle: 0, width: 0.18, color: "#5fb0c0", opacity: 0.32, chorus: 0.6 }, // the horizon
      { light: "glow", at: [0.5, 0.46], size: [0.65, 0.35], color: "#e0fbff", opacity: 0.18, chorus: 0.6 }, // the sun
      { light: "band", at: [0.5, 0.82], angle: 0, width: 0.4, color: "#8fa8b0", opacity: 0.12, chorus: 0.18 }, // the field
    ],
    chorus: { count: 2, drift: [3, -15], opacity: 1.5, rays: 0.15, burst: { count: 16, from: "everywhere" } },
    // the chorus three times (the same music each time), then the big part near the end
    chorusTimes: ["1:23.2-2:04.9", "2:15.4-2:46.7", "3:41.4-4:13.4", "4:54.8-5:36.6"],
  },
  "planetary-fields-milestone": "planetary-fields-final-ver", // an earlier version of the same song
};
