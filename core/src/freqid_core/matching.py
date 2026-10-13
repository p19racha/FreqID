# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
matching.py: Pure-NumPy biometric matching and threshold evaluation routines.

Contains zero PyTorch or image dependencies. Operates strictly on unit-normalized
embedding vectors.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from freqid_core.errors import DimensionMismatchError


@dataclass(frozen=True)
class MatchResult:
    """Result of a 1:N biometric identification query."""
    target_id: str
    similarity: float
    is_match: bool
    rank: int


def cosine_similarity(
    a: np.ndarray,
    b: np.ndarray,
) -> float | np.ndarray:
    """
    Computes cosine similarity between embeddings.

    Supports:
    - Two 1D vectors (512,) and (512,) -> float
    - One 1D vector (512,) and a 2D matrix (N, 512) -> 1D array of shape (N,)
    - Two 2D matrices (N, 512) and (N, 512) -> 1D array of pairwise scores (N,)

    Automatically ensures L2 normalization before computation.
    """
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)

    if a.shape[-1] != b.shape[-1]:
        raise DimensionMismatchError(
            f"Embedding feature dimensions mismatch: {a.shape[-1]} vs {b.shape[-1]}"
        )

    # 1D vs 1D
    if a.ndim == 1 and b.ndim == 1:
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        score = float(np.dot(a, b) / (norm_a * norm_b))
        return float(np.clip(score, -1.0, 1.0))

    # 1D query vs 2D gallery
    elif a.ndim == 1 and b.ndim == 2:
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b, axis=1)
        if norm_a == 0:
            return np.zeros(len(b), dtype=np.float32)
        norm_b = np.where(norm_b == 0, 1e-12, norm_b)
        scores = np.dot(b, a) / (norm_b * norm_a)
        return np.clip(scores, -1.0, 1.0)

    # 2D batch vs 2D batch
    elif a.ndim == 2 and b.ndim == 2:
        if a.shape[0] != b.shape[0]:
            raise DimensionMismatchError(
                f"Batch sizes mismatch: {a.shape[0]} vs {b.shape[0]}"
            )
        norm_a = np.linalg.norm(a, axis=1)
        norm_b = np.linalg.norm(b, axis=1)
        norm_a = np.where(norm_a == 0, 1e-12, norm_a)
        norm_b = np.where(norm_b == 0, 1e-12, norm_b)
        scores = np.sum(a * b, axis=1) / (norm_a * norm_b)
        return np.clip(scores, -1.0, 1.0)

    else:
        raise DimensionMismatchError(
            f"Unsupported array dimensions for cosine similarity: {a.ndim}D and {b.ndim}D"
        )


def verify(
    embedding_a: np.ndarray,
    embedding_b: np.ndarray,
    threshold: float = 0.35,
) -> tuple[float, bool]:
    """
    1:1 biometric verification between two embeddings.

    Args:
        embedding_a: Query embedding (512,).
        embedding_b: Reference embedding (512,).
        threshold: Decision threshold (default: 0.35).

    Returns:
        (cosine_similarity, is_match)
    """
    score = float(cosine_similarity(embedding_a, embedding_b))
    is_match = score >= threshold
    return score, is_match


def identify(
    query_embedding: np.ndarray,
    gallery_embeddings: np.ndarray,
    gallery_ids: Sequence[str],
    threshold: float = 0.35,
    top_k: int = 5,
) -> list[MatchResult]:
    """
    1:N biometric identification against an enrolled gallery.

    Args:
        query_embedding: Query embedding of shape (512,).
        gallery_embeddings: Gallery array of shape (N, 512).
        gallery_ids: List of N identifier strings corresponding to gallery items.
        threshold: Decision threshold for affirmative match flag.
        top_k: Maximum number of ranked results to return.

    Returns:
        List of MatchResult objects sorted in descending order of similarity.
    """
    query = np.asarray(query_embedding, dtype=np.float32)
    gallery = np.asarray(gallery_embeddings, dtype=np.float32)

    if gallery.size == 0 or len(gallery_ids) == 0:
        return []

    if gallery.ndim != 2:
        raise DimensionMismatchError(
            f"Gallery embeddings must be 2D matrix (N, 512), got shape {gallery.shape}"
        )

    if len(gallery) != len(gallery_ids):
        raise ValueError(
            f"Gallery count ({len(gallery)}) must equal gallery_ids count ({len(gallery_ids)})"
        )

    scores = cosine_similarity(query, gallery)
    assert isinstance(scores, np.ndarray)

    k = min(top_k, len(scores))
    ranked_indices = np.argsort(scores)[::-1][:k]

    results: list[MatchResult] = []
    for rank, idx in enumerate(ranked_indices, start=1):
        score = float(scores[idx])
        results.append(
            MatchResult(
                target_id=str(gallery_ids[idx]),
                similarity=score,
                is_match=(score >= threshold),
                rank=rank,
            )
        )

    return results


def compute_decision_threshold(
    genuine_scores: np.ndarray,
    impostor_scores: np.ndarray,
    target_far: float = 0.001,
) -> float:
    """
    Computes the operating threshold that achieves a target False Accept Rate (FAR).

    FAR is the fraction of impostor pairs whose similarity is >= threshold.
    """
    impostors = np.sort(np.asarray(impostor_scores, dtype=np.float32))
    n_impostors = len(impostors)
    if n_impostors == 0:
        raise ValueError("impostor_scores array cannot be empty")

    # Target index in sorted array where (1 - index/n) <= target_far
    # i.e., index >= n * (1 - target_far)
    target_idx = int(np.ceil((1.0 - target_far) * n_impostors))
    target_idx = min(max(target_idx, 0), n_impostors - 1)

    threshold = float(impostors[target_idx])
    return threshold
