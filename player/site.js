// The text and links on the website. Edit them here; anything left empty ("") is hidden.
// Song titles, albums, track order, and per-song store links live in data/catalog.csv.

export const SITE = {
  // Where the published site sends listening events: the listening API on Cloudflare (worker/;
  // README.md, "Running the listening API online"). Empty, nothing is sent. python app/server.py on
  // this computer tells the page its own address, which comes first; the local preview (serve.py)
  // sends here, and the API turns it away (it takes only the published site's pages).
  eventsUrl: "https://synopsist-events.oslohaggadone.workers.dev/events",

  artist: "Oslo Haggadone",
  tagline: "Independent artist. Every song, free to stream.",

  // A few sentences about you, shown below the title screen and in the About section. Leave empty to
  // hide them.
  bio: "",

  // A few short points below the title screen, shown when you scroll down: a title and a sentence
  // each. Leave the list empty ([]) to hide them.
  summary: [
    { title: "Every song, free", text: "Every release, plus unreleased songs. No account, no ads." },
    { title: "For artists and producers", text: "Built with artists and music producers in mind, and open to anyone who enjoys music." },
    { title: "Playlists from your moments", text: "Synopsist anonymously notes the moments you replay, to build playlists of songs that resonate with your taste." },
  ],

  // Your most popular songs, most played first (their track ids, from data/catalog.csv), for the
  // music page's "Most popular" order; songs not listed follow in the usual order. Your streaming
  // stats (Spotify or Apple Music for Artists) have the numbers. Once the site keeps listening data,
  // its own plays can rank them instead.
  popular: [
    "hollow-journey", "into-space", "spacial-awareness", "journey", "flowers-about", "facades",
    "eternal-synopsis", "planetary-fields-final-ver",
  ],

  // How many times each song has been streamed, shown on its row and beside it while it plays: put
  // each number in place of its null (no quotes or commas: 12345). Copy them from your streaming
  // stats (Amuse adds up every store; Spotify shows each song's plays), and put the day you took them
  // in streamsAsOf, as "2026-10-24". A song left at null shows no number. Once the site keeps its own
  // listening data (ROADMAP, Phase 3), it can count its own plays too.
  streams: {
    // Eternal Synopsis Single
    "eternal-synopsis": null,
    // Hollow Journey Beyond
    "hollow-journey-beyond": null,
    "volition": null,
    "crimson-eclipse": null,
    "impulse": null,
    "flowers-about": null,
    "planetary-fields-2024-remastered-version": null,
    "jiggly-cake": null,
    "glistening-dawn": null,
    "you-know-what-that-means": null,
    "facades": null,
    "journey": null,
    "dying-light": null,
    // Planetary Fields
    "planetary-fields-final-ver": null,
    "planetary-fields-milestone": null,
    // Hollow Journey
    "hollow-journey": null,
    "electric-space": null,
    "into-space": null,
    "space-rain": null,
    "zero-gravity": null,
    "negative-space": null,
    "tropical-space-day": null,
    "tropical-space-day-extended": null,
    "bad-boy": null,
    "spacial-awareness": null,
    "delta-gravity-delta-side": null,
    "hollow-truth": null,
  },
  streamsAsOf: "",

  // Your profile picture, used as the site's logo (a square image in player/images/). The small
  // logo in the top bar uses a close-up so it stays recognizable at that size.
  logo: "images/profile.jpg",
  logoSmall: "images/icon-180.png",

  // Your profiles, shown as "Also on" links. Paste the full links, starting with https://
  links: {
    spotify: "https://open.spotify.com/artist/04dhGsn2LanFxfQAyJD0JH",
    appleMusic: "https://music.apple.com/ca/artist/oslo-haggadone/1714145569",
    amazonMusic: "https://www.amazon.com/music/player/artists/B0D8B6WF4L/oslo-haggadone",
    youtube: "https://www.youtube.com/@oslohaggadone",
    instagram: "",
    tiktok: "",
  },
};
