// The text and links on the website. Edit them here; anything left empty ("") is hidden.
// Song titles, albums, track order, and per-song store links live in data/catalog.csv.

export const SITE = {
  artist: "Oslo Haggadone",
  tagline: "Independent artist. Every song, free to stream.",

  // A few sentences about you, shown below the title screen and in the About section. Leave empty to
  // hide them.
  bio: "",

  // A few short points below the title screen, shown when you scroll down: a title and a sentence
  // each. Leave the list empty ([]) to hide them.
  summary: [
    { title: "Every song, free", text: "Every release, plus unreleased songs. No account, no ads." },
    { title: "Made for listening", text: "In full screen, the light behind the cover follows the music, and each song's details show what's in it, moment by moment." },
    { title: "The moments you replay", text: "The player notes which parts of each song people replay, so Oslo can see what lands. It's anonymous, and you can turn it off in Settings." },
  ],

  // Your most popular songs, most played first (their track ids, from data/catalog.csv), for the
  // music page's "Most popular" order; songs not listed follow in the usual order. Your streaming
  // stats (Spotify or Apple Music for Artists) have the numbers. Once the site keeps listening data,
  // its own plays can rank them instead.
  popular: [
    "hollow-journey", "into-space", "spacial-awareness", "journey", "flowers-about", "facades",
    "eternal-synopsis", "planetary-fields-final-ver",
  ],

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
