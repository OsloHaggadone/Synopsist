"""Paths and settings shared across Synopsist."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
STREAM_DIR = DATA_DIR / "stream"  # the MP3s, one folder per album
CATALOG_CSV = DATA_DIR / "catalog.csv"  # one row per song; the only tracked file in data/
ANALYSIS_DIR = DATA_DIR / "analysis"  # cached frame-level audio analysis, one .npz per audio file
DB_PATH = DATA_DIR / "synopsist.db"
MODELS_DIR = ROOT / "models"

PLAYER_DIR = ROOT / "player"  # the website
LIBRARY_DIR = PLAYER_DIR / "library"  # written by scripts/build_catalog.py for the website; don't edit

# The website's copies of the songs are volume-matched to this loudness, like Spotify's default, so
# shuffling between albums doesn't jump in volume. The change is lossless (see mp3gain.py) and the
# files in data/stream/ are never touched. None keeps every song at its original level.
STREAM_LUFS = -14.0

# Where the website loads songs from. Empty means the copies in player/library/audio/ (a clone of the
# private repository OsloHaggadone/synopsist-audio), published with the site. Only if they ever move
# to cloud storage, put the bucket's public URL here, ending in a slash.
AUDIO_BASE_URL = ""

# Who a song is by when its row in data/catalog.csv doesn't say (the artist column, filled in with
# this for every song; change a song's own there, for a collaboration, or another artist's songs).
ARTIST = "Oslo Haggadone"

# Your artist page on Apple Music. scripts/import_apple_music.py reads Apple's public catalog for it
# to fill in release dates, song links, track order, and album covers. The country is the store
# the song links point to.
APPLE_MUSIC_ARTIST_ID = "1714145569"
APPLE_MUSIC_COUNTRY = "ca"

# Length of a segment, the unit that listening data and audio features are matched on.
# Changing it and rerunning scripts/build_catalog.py re-cuts every song from the analysis cache
# (seconds, no audio decoding).
WINDOW_S = 4.0
