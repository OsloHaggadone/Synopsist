"""Run the whole offline pipeline with one command:

1. sync data/catalog.csv with the MP3s in data/stream/<album>/
2. register every song in the database (data/synopsist.db)
3. analyze new or changed audio with Essentia, in parallel (cached in data/analysis/)
4. cut every song into segments and store song-level and segment-level features
5. publish the website's music library in player/library/ (song list, volume-matched audio, covers,
   and each song's analysis for its backgrounds, seek bar wave, and details panel)

Rerunning is cheap: unchanged songs are skipped, and a new segment length (WINDOW_S in
src/synopsist/config.py) re-cuts every song from the cache without decoding audio.

Usage: python scripts/build_catalog.py [--jobs N] [--force]
"""

import argparse
import multiprocessing
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synopsist import db, embed, ingest, publish
from synopsist.config import ANALYSIS_DIR, DB_PATH, STREAM_DIR, STREAM_LUFS, WINDOW_S
from synopsist.segment import segment_bounds


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze every song and fill the database.")
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1),
                        help="songs to analyze in parallel (default: %(default)s)")
    parser.add_argument("--force", action="store_true", help="redo the audio analysis even if cached")
    args = parser.parse_args()
    started = time.perf_counter()

    try:
        rows = ingest.sync_catalog()
    except ingest.CatalogError as e:
        print(e)
        return 1

    conn = db.connect()
    for track_id in ingest.register_tracks(conn, rows):
        print(f"Removed {track_id} from the database (no longer in the catalog)")

    # A song needs work if its audio, the analysis code, or the segment length changed.
    hashes = {row["track_id"]: ingest.file_sha1(STREAM_DIR / row["file"]) for row in rows}
    stored = {r["track_id"]: (r["file_sha1"], r["analysis_version"], r["window_s"])
              for r in conn.execute("SELECT track_id, file_sha1, analysis_version, window_s FROM tracks")}
    todo = [row for row in rows if args.force
            or stored[row["track_id"]] != (hashes[row["track_id"]], embed.ANALYSIS_VERSION, WINDOW_S)]

    def store(row: dict, analysis: dict) -> None:
        bounds = segment_bounds(analysis["duration_s"], WINDOW_S)
        db.save_analysis(conn, row["track_id"], embed.track_features(analysis),
                         embed.segment_features(analysis, bounds), file_sha1=hashes[row["track_id"]],
                         analysis_version=embed.ANALYSIS_VERSION, window_s=WINDOW_S)

    to_analyze = []
    for row in todo:
        if args.force:
            embed.cache_path(hashes[row["track_id"]]).unlink(missing_ok=True)
        cached = embed.load_cached(hashes[row["track_id"]])
        if cached is None:
            to_analyze.append(row)
        else:
            store(row, cached)
    if len(todo) > len(to_analyze):
        print(f"Re-cut {len(todo) - len(to_analyze)} songs from the analysis cache")

    failures = []
    if to_analyze:
        embed.ensure_models()  # download once, before the workers start
        jobs = max(1, min(args.jobs, len(to_analyze)))
        print(f"Analyzing {len(to_analyze)} songs ({jobs} at a time)...")
        # spawn, not fork: TensorFlow can deadlock in a forked process
        with ProcessPoolExecutor(jobs, mp_context=multiprocessing.get_context("spawn")) as pool:
            futures = {pool.submit(embed.analyze_cached, STREAM_DIR / row["file"], hashes[row["track_id"]]): row
                       for row in to_analyze}
            for n, future in enumerate(as_completed(futures), 1):
                row = futures[future]
                try:
                    store(row, future.result())
                except Exception as e:
                    failures.append(row["track_id"])
                    print(f"  [{n}/{len(to_analyze)}] FAILED {row['file']}: {e}")
                else:
                    print(f"  [{n}/{len(to_analyze)}] {row['title']}")

    # Drop cached analyses of audio that is no longer in the catalog.
    keep = set(hashes.values())
    for path in ANALYSIS_DIR.glob("*"):
        if path.stem not in keep or path.suffix != ".npz":
            path.unlink()

    site = publish.publish(conn)
    volume = (f"volume matched to {STREAM_LUFS:g} LUFS ({site['lowered']} turned down, {site['raised']} up, "
              f"{site['unchanged']} unchanged; {site['limited_by_peak']} quiet ones raised only as far as their peaks allow)"
              if STREAM_LUFS is not None else "original volume")
    print(f"Website library: {site['songs']} songs in {site['albums']} albums, {site['new_files']} new audio files, {volume}")
    for track_id in site["not_adjustable"]:
        print(f"  {track_id}: not a standard MP3, published at its original volume")

    songs, minutes = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(duration_s), 0) / 60 FROM tracks WHERE analyzed_at IS NOT NULL").fetchone()
    segments = conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
    conn.close()
    print(f"Done in {time.perf_counter() - started:.0f}s: {songs} songs ({minutes:.0f} min of audio), "
          f"{segments} segments of {WINDOW_S:g}s, in {DB_PATH.relative_to(DB_PATH.parents[1])}")
    if failures:
        print("Failed: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
