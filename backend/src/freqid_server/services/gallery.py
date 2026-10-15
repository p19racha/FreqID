# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
gallery.py: High-speed in-memory vector index cache with copy-on-write concurrency safety.
"""

from __future__ import annotations

import asyncio

import freqid_core as fq
import numpy as np
from freqid_core.matching import MatchResult

from freqid_server.logging import logger
from freqid_server.storage.base import TemplateStore


class GalleryIndex:
    """
    In-memory vector gallery optimized for sub-10ms 1:N brute-force cosine identification.
    Uses copy-on-write for thread-safe concurrent search during enrollments and deletions.
    """

    def __init__(self) -> None:
        self._user_ids: list[str] = []
        self._embeddings_matrix: np.ndarray | None = None  # Shape (N, 512)
        self._lock = asyncio.Lock()

    @property
    def count(self) -> int:
        return len(self._user_ids)

    @property
    def identities(self) -> list[str]:
        return list(self._user_ids)

    async def load_from_store(self, store: TemplateStore) -> int:
        """Loads all active templates from storage into memory."""
        async with self._lock:
            templates = await store.list_templates()
            if not templates:
                self._user_ids = []
                self._embeddings_matrix = None
                return 0

            ids = [t.user_id for t in templates]
            embs = np.stack([t.embedding for t in templates], axis=0).astype(np.float32)

            self._user_ids = ids
            self._embeddings_matrix = embs
            logger.info(f"Loaded {len(ids)} identity templates into in-memory gallery.")
            return len(ids)

    async def add_or_update(self, user_id: str, embedding: np.ndarray) -> None:
        """Adds or updates a template embedding in the gallery using copy-on-write."""
        norm_emb = embedding.astype(np.float32)
        norm_val = np.linalg.norm(norm_emb)
        if norm_val > 0:
            norm_emb = norm_emb / norm_val

        async with self._lock:
            ids = list(self._user_ids)
            if user_id in ids:
                idx = ids.index(user_id)
                assert self._embeddings_matrix is not None
                new_matrix = self._embeddings_matrix.copy()
                new_matrix[idx] = norm_emb
            else:
                ids.append(user_id)
                if self._embeddings_matrix is None or len(self._embeddings_matrix) == 0:
                    new_matrix = norm_emb.reshape(1, 512)
                else:
                    new_matrix = np.vstack([self._embeddings_matrix, norm_emb.reshape(1, 512)])

            # Atomic swap
            self._user_ids = ids
            self._embeddings_matrix = new_matrix

    async def remove(self, user_id: str) -> bool:
        """Removes a user identity from the gallery using copy-on-write."""
        async with self._lock:
            if user_id not in self._user_ids:
                return False

            idx = self._user_ids.index(user_id)
            ids = list(self._user_ids)
            ids.pop(idx)

            if not ids or self._embeddings_matrix is None:
                new_matrix = None
            else:
                new_matrix = np.delete(self._embeddings_matrix, idx, axis=0)

            # Atomic swap
            self._user_ids = ids
            self._embeddings_matrix = new_matrix
            return True

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5,
        threshold: float = 0.35,
        score_floor: float = 0.20,
    ) -> list[MatchResult]:
        """
        Executes 1:N biometric search against current snapshot of the gallery.
        Safe to call concurrently without locking since arrays are immutable once assigned.
        """
        matrix = self._embeddings_matrix
        ids = self._user_ids

        if matrix is None or len(ids) == 0:
            return []

        # Vectorized cosine search via freqid_core.matching
        results = fq.identify(
            query_embedding=query_embedding,
            gallery_embeddings=matrix,
            gallery_ids=ids,
            threshold=threshold,
            top_k=top_k,
        )

        # Filter candidates below minimum score floor
        filtered = [r for r in results if r.similarity >= score_floor]
        return filtered
