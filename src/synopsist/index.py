"""Nearest-neighbor search over segment embeddings.

Brute-force cosine similarity: a catalog of a few thousand segments searches in well under a
millisecond, so no approximate index is needed.
"""

import sqlite3

import numpy as np

from synopsist.db import from_blob


class SegmentIndex:
    def __init__(self, conn: sqlite3.Connection):
        rows = conn.execute(
            """SELECT s.track_id, s.idx, s.start_s, s.end_s, s.embedding, t.title
               FROM segments s JOIN tracks t USING (track_id)
               ORDER BY t.album, t.title, s.idx"""
        ).fetchall()
        if not rows:
            raise ValueError("No segments in the database yet: run scripts/build_catalog.py")
        self.track_ids = np.array([r["track_id"] for r in rows])
        self.idx = np.array([r["idx"] for r in rows])
        self.start_s = np.array([r["start_s"] for r in rows])
        self.end_s = np.array([r["end_s"] for r in rows])
        self.titles = np.array([r["title"] for r in rows])
        vectors = np.stack([from_blob(r["embedding"]) for r in rows])
        # Every piece of music shares a large common component; removing the catalog average
        # makes the differences between segments dominate the similarity.
        self.center = vectors.mean(axis=0)
        self.vectors = self.normalize(vectors)
        self.position = {(t, int(i)): n for n, (t, i) in enumerate(zip(self.track_ids, self.idx))}

    def __len__(self) -> int:
        return len(self.vectors)

    def normalize(self, vectors: np.ndarray) -> np.ndarray:
        """Center and L2-normalize raw embeddings (one or many) so dot products are cosines."""
        centered = np.atleast_2d(vectors) - self.center
        return centered / np.maximum(np.linalg.norm(centered, axis=1, keepdims=True), 1e-12)

    def vector(self, track_id: str, idx: int) -> np.ndarray:
        return self.vectors[self.position[(track_id, idx)]]

    def search(self, query: np.ndarray, k: int = 10, exclude_tracks=()) -> list[dict]:
        """Top-k segments by cosine similarity to an already normalized query vector."""
        scores = self.vectors @ query
        if len(exclude_tracks):
            scores[np.isin(self.track_ids, list(exclude_tracks))] = -np.inf
        k = min(k, int(np.isfinite(scores).sum()))
        top = np.argpartition(-scores, k - 1)[:k] if k else []
        top = sorted(top, key=lambda n: -scores[n])
        return [{"track_id": str(self.track_ids[n]), "title": str(self.titles[n]), "idx": int(self.idx[n]),
                 "start_s": float(self.start_s[n]), "end_s": float(self.end_s[n]), "score": float(scores[n])}
                for n in top]

    def neighbors(self, track_id: str, idx: int, k: int = 10, other_tracks: bool = True) -> list[dict]:
        """Segments most similar to one segment, from other songs only by default."""
        query = self.vector(track_id, idx)
        if other_tracks:
            return self.search(query, k, exclude_tracks=[track_id])
        hits = self.search(query, k + 1)
        return [h for h in hits if (h["track_id"], h["idx"]) != (track_id, idx)][:k]
