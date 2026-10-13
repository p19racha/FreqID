# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_matching.py: Unit tests for cosine similarity, 1:1 verify, 1:N identify, and thresholds.
"""

import numpy as np
import pytest

from freqid_core.errors import DimensionMismatchError
from freqid_core.matching import (
    compute_decision_threshold,
    cosine_similarity,
    identify,
    verify,
)


def test_cosine_similarity_known_vectors():
    # Identical vectors
    v1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    assert np.isclose(cosine_similarity(v1, v1), 1.0)

    # Orthogonal vectors
    v2 = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    assert np.isclose(cosine_similarity(v1, v2), 0.0)

    # Opposite vectors
    v3 = np.array([-1.0, 0.0, 0.0], dtype=np.float32)
    assert np.isclose(cosine_similarity(v1, v3), -1.0)


def test_verify_decision():
    v1 = np.array([1.0, 0.0], dtype=np.float32)
    v2 = np.array([0.0, 1.0], dtype=np.float32)

    score, is_match = verify(v1, v1, threshold=0.8)
    assert np.isclose(score, 1.0)
    assert is_match is True

    score2, is_not_match = verify(v1, v2, threshold=0.5)
    assert np.isclose(score2, 0.0)
    assert is_not_match is False


def test_identify_ranking():
    query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    gallery = np.array(
        [
            [0.0, 1.0, 0.0],  # id_ortho: sim = 0.0
            [0.9, 0.1, 0.0],  # id_close: sim ~ 0.99
            [-1.0, 0.0, 0.0], # id_opp: sim = -1.0
        ],
        dtype=np.float32,
    )
    ids = ["id_ortho", "id_close", "id_opp"]

    results = identify(query, gallery, ids, threshold=0.5, top_k=2)
    assert len(results) == 2
    assert results[0].target_id == "id_close"
    assert results[0].is_match is True
    assert results[0].rank == 1

    assert results[1].target_id == "id_ortho"
    assert results[1].is_match is False
    assert results[1].rank == 2


def test_threshold_calibration_synthetic():
    np.random.seed(42)
    # Genuine scores centered around 0.85
    genuine = np.random.normal(loc=0.85, scale=0.05, size=1000)
    # Impostor scores centered around 0.10
    impostor = np.random.normal(loc=0.10, scale=0.05, size=1000)

    threshold = compute_decision_threshold(genuine, impostor, target_far=0.001)

    # FAR check: impostors >= threshold should be <= 1 / 1000
    actual_far = np.mean(impostor >= threshold)
    assert actual_far <= 0.002
    assert threshold > 0.20


def test_matching_dimension_mismatch():
    v1 = np.zeros(512, dtype=np.float32)
    v2 = np.zeros(256, dtype=np.float32)

    with pytest.raises(DimensionMismatchError):
        cosine_similarity(v1, v2)
