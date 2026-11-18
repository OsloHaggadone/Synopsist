"""Replay heatmaps for posts (ROADMAP, Artist phases 3 and 5): for each of the most popular songs, its
wave with the parts listeners replay lit up, and the part replayed most marked, as a square picture
(1080 x 1080) in the site's look: "the part everyone loops".

It reads the replays as the backend counts them (src/synopsist/events.py, jumps_back): a stretch of a
song counts once per listener, however often they looped it, so one keen listener can't make a peak.
A song is drawn only once at least MIN_LISTENERS listeners have replayed part of it; until then it
says how many have. Simulated listening (data/simulated.db, scripts/simulate_events.py) is never shown
as real: any picture made from it is stamped "Simulated data", for trying the design only, and
simulated listeners in another database are left out.

Run:  python scripts/make_heatmaps.py                       the real listening (data/live.db: run
                                                            scripts/pull_events.py first)
      python scripts/make_heatmaps.py --db data/simulated.db   previews of the design, stamped
      python scripts/make_heatmaps.py --songs facades journey  other songs (default: site.js's popular)
Then the pictures, from the pages it writes in data/heatmaps/:
      "/mnt/c/Program Files/nodejs/node.exe" scripts/render_heatmaps.mjs "$(wslpath -w data/heatmaps)"
"""

import argparse
import base64
import html
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synopsist import db, events  # noqa: E402
from synopsist.config import DATA_DIR, LIBRARY_DIR, PLAYER_DIR  # noqa: E402
from synopsist.simulate import SIM_MARK  # noqa: E402

OUT = DATA_DIR / "heatmaps"
MIN_LISTENERS = 5  # who replayed part of the song, before it's drawn from real listening
PEAK_S = 10  # the stretch marked as replayed most
SIZE = 1080


def clock(seconds: float) -> str:
    whole = int(round(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


def heat_of(replays: list[dict], duration: float) -> tuple[list[int], set[str]]:
    """How many listeners replayed each second of a song, and who."""
    seconds = [set() for _ in range(math.ceil(duration))]
    for replay in replays:
        for second in range(int(replay["to_s"]), min(len(seconds), math.ceil(replay["from_s"]))):
            seconds[second].add(replay["user_id"])
    return [len(who) for who in seconds], set().union(*seconds) if seconds else set()


def peak(heat: list[int]) -> tuple[int, int]:
    """The PEAK_S seconds replayed most: (start, end)."""
    width = min(PEAK_S, len(heat))
    best = max(range(len(heat) - width + 1), key=lambda start: sum(heat[start:start + width]))
    return best, best + width


def data_url(path: Path, kind: str) -> str:
    return f"data:{kind};base64,{base64.b64encode(path.read_bytes()).decode()}"


def page(song: dict, album: dict, wave: list[int], heat: list[int], listeners: int, simulated: bool) -> str:
    """One song's picture, as a page with everything in it (fonts and cover too)."""
    duration = song["duration"]
    start, end = peak(heat)
    hottest = max(heat) or 1
    width, height, gap = 960, 300, 2
    bar = width / len(wave)
    bars = []
    for i, level in enumerate(wave):
        at = (i + 0.5) / len(wave) * duration
        warmth = heat[min(len(heat) - 1, int(at))] / hottest  # 0 (not replayed) to 1 (most)
        tall = max(4, level / 100 * height)
        # one hue: the dim blue of the page to the moon's white-blue
        light = 16 + 70 * warmth ** 0.8
        sat = 30 + 55 * warmth
        bars.append(f'<rect x="{i * bar + gap / 2:.1f}" y="{height - tall:.1f}" width="{bar - gap:.1f}" height="{tall:.1f}" '
                    f'rx="1.5" fill="hsl(207 {sat:.0f}% {light:.0f}%)"/>')
    left, right = start / duration * width, end / duration * width
    stamp = ('<div class="stamp">Simulated data · not real listening · design preview</div>' if simulated else "")
    fonts = PLAYER_DIR / "fonts"
    cover = LIBRARY_DIR / album["cover"] if album.get("cover") else None
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@font-face {{ font-family: Exo; src: url({data_url(fonts / "exo-variable.woff2", "font/woff2")}); font-weight: 100 900; }}
@font-face {{ font-family: Kazesawa; src: url({data_url(fonts / "kazesawa-regular.woff2", "font/woff2")}); }}
@font-face {{ font-family: Kazesawa; src: url({data_url(fonts / "kazesawa-semibold.woff2", "font/woff2")}); font-weight: 600; }}
* {{ box-sizing: border-box; margin: 0; }}
body {{ width: {SIZE}px; height: {SIZE}px; overflow: hidden; color: #ecf4fd; font: 400 26px Kazesawa, sans-serif;
  background: radial-gradient(70% 55% at 82% 8%, #12355a 0%, #071325 55%, #050b15 100%); }}
.card {{ position: absolute; inset: {110 if simulated else 60}px 60px 60px; display: flex; flex-direction: column; }}
.kicker {{ color: #43abf5; font: 600 24px Exo, sans-serif; letter-spacing: 0.22em; text-transform: uppercase; }}
.kicker::before {{ content: ""; display: inline-block; width: 14px; height: 14px; margin-right: 16px; background: #43abf5;
  transform: rotate(45deg) translateY(-3px); }}
.song {{ display: flex; gap: 36px; align-items: center; margin-top: 44px; }}
.song img {{ width: 220px; height: 220px; border-radius: 4px; object-fit: cover; box-shadow: 0 18px 50px rgba(0,0,0,.5); }}
h1 {{ font: 650 72px/1.05 Exo, sans-serif; }}
.by {{ margin-top: 14px; color: #a1b9d3; font-size: 28px; }}
.chart {{ position: relative; margin-top: auto; }}
.mark {{ position: absolute; top: -78px; left: {left:.1f}px; width: {right - left:.1f}px; text-align: center; white-space: nowrap; }}
.mark b {{ display: block; color: #d5eaff; font: 650 30px Exo, sans-serif; }}
.mark span {{ color: #a1b9d3; font-size: 22px; }}
.mark::after {{ content: ""; position: absolute; left: 0; right: 0; bottom: -14px; height: 8px; border: 2px solid #d5eaff;
  border-bottom: 0; border-radius: 3px 3px 0 0; }}
.axis {{ display: flex; justify-content: space-between; margin-top: 14px; color: #7890ae; font: 500 22px Exo, sans-serif; }}
.foot {{ display: flex; justify-content: space-between; margin-top: 40px; color: #a1b9d3; font-size: 24px; }}
.foot b {{ color: #ecf4fd; font-weight: 600; }}
.stamp {{ position: absolute; top: 0; left: 0; right: 0; padding: 14px; background: #ffb020; color: #1a1200; text-align: center;
  font: 700 26px Exo, sans-serif; letter-spacing: 0.06em; text-transform: uppercase; z-index: 2; }}
</style></head><body>{stamp}<div class="card">
<p class="kicker">The part everyone loops</p>
<div class="song">{f'<img src="{data_url(cover, "image/jpeg")}" alt="">' if cover and cover.exists() else ""}
<div><h1>{html.escape(song["title"])}</h1><p class="by">{html.escape(song["artist"])} · {html.escape(album["title"])}</p></div></div>
<div class="chart"><div class="mark"><b>{clock(start)}–{clock(end)}</b><span>replayed most</span></div>
<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">{"".join(bars)}</svg>
<div class="axis"><span>0:00</span><span>{clock(duration / 2)}</span><span>{clock(duration)}</span></div></div>
<div class="foot"><span><b>{listeners}</b> listeners replayed parts of it</span><span>oslohaggadone.com/Synopsist</span></div>
</div></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay heatmaps of the most popular songs, for posts.")
    parser.add_argument("--db", type=Path, default=DATA_DIR / "live.db", help="the listening (default data/live.db)")
    parser.add_argument("--songs", nargs="+", help="track ids (default: site.js's most popular)")
    args = parser.parse_args()
    if not args.db.exists():
        print(f"No database at {args.db}" + (": run python scripts/pull_events.py first" if args.db.name == "live.db" else ""))
        return 1
    catalog = json.loads((LIBRARY_DIR / "catalog.json").read_text(encoding="utf-8"))
    songs = {track["id"]: track for track in catalog["tracks"]}
    albums = {album["id"]: album for album in catalog["albums"]}
    site = (PLAYER_DIR / "site.js").read_text(encoding="utf-8")
    wanted = args.songs or re.findall(r'"([\w-]+)"', re.search(r"popular:\s*\[(.*?)\]", site, re.S)[1])

    conn = db.connect(args.db)
    replays = events.jumps_back(conn)
    conn.close()
    simulated = any(replay["user_id"].endswith(SIM_MARK) for replay in replays)
    if simulated:
        print("Simulated listening: every picture is stamped as such, for trying the design only.")
    else:
        replays = [replay for replay in replays if not replay["user_id"].endswith(SIM_MARK)]

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.html"):
        old.unlink()
    made = 0
    for song_id in wanted:
        song = songs.get(song_id)
        if not song:
            print(f"  {song_id}: not in the catalog")
            continue
        heat, who = heat_of([r for r in replays if r["track_id"] == song_id], song["duration"])
        if not who or (not simulated and len(who) < MIN_LISTENERS):
            print(f"  {song['title']}: not yet ({len(who)} of {MIN_LISTENERS} listeners have replayed part of it)")
            continue
        analysis = json.loads((LIBRARY_DIR / song["analysis"]).read_text(encoding="utf-8"))
        name = f"{song_id}{'-SIMULATED' if simulated else ''}.html"
        (OUT / name).write_text(page(song, albums[song["album"]], analysis["wave"], heat, len(who), simulated), encoding="utf-8")
        start, end = peak(heat)
        print(f"  {song['title']}: replayed most {clock(start)}–{clock(end)}, by {len(who)} listeners")
        made += 1
    if made:
        print(f"\n{made} page(s) in {OUT}. The pictures:\n"
              f'  "/mnt/c/Program Files/nodejs/node.exe" scripts/render_heatmaps.mjs "$(wslpath -w {OUT})"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
