# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_score_leakage.py: Tests for decision-only output, score quantization/noise, and near-threshold anomaly detection.
"""

from __future__ import annotations

import numpy as np

from freqid_server.services.anomaly_detector import NearThresholdAnomalyDetector
from freqid_server.services.matching import MatchingService
from freqid_server.storage.base import EnrolledTemplate


def test_score_quantization_and_laplace_noise():
    raw_scores = [0.3341, 0.3582, 0.4129, 0.1234, -0.052]
    rng = np.random.default_rng(1234)

    for s in raw_scores:
        noised = MatchingService.quantize_and_noise_score(s, step=0.05, epsilon=2.0, rng=rng)
        assert -1.0 <= noised <= 1.0
        # Check precision
        assert round(noised, 3) == noised

    # Statistical test of Laplace noise variance
    samples = [
        MatchingService.quantize_and_noise_score(0.35, step=0.05, epsilon=2.0, rng=rng)
        for _ in range(1000)
    ]
    mean_val = float(np.mean(samples))
    std_val = float(np.std(samples))

    # Mean should be close to 0.35 (step=0.05 has 0.35 on grid)
    assert abs(mean_val - 0.35) < 0.05
    # Theoretical std for Laplace with scale b=0.025 is b * sqrt(2) ~ 0.035
    assert 0.015 < std_val < 0.065


def test_decision_only_verification_masks_similarity():
    service = MatchingService(active_model_version="v1.0-ir18")
    emb_a = np.ones(512, dtype=np.float32) / np.sqrt(512)
    emb_b = np.ones(512, dtype=np.float32) / np.sqrt(512)

    template = EnrolledTemplate(
        user_id="user-1",
        template_id="t-1",
        embedding=emb_b,
        model_version="v1.0-ir18",
        enrolled_at_iso="2026-10-15T00:00:00Z",
        frames_used=5,
    )

    # When mask_scores=True (production default for standard callers)
    is_match, sim = service.verify(
        query_embedding=emb_a,
        claimed_identity="user-1",
        template=template,
        threshold=0.35,
        mask_scores=True,
    )
    assert is_match is True
    assert sim is None, "Similarity score leaked in decision-only mode!"

    # When mask_scores=False (diagnostic / admin mode)
    is_match, sim = service.verify(
        query_embedding=emb_a,
        claimed_identity="user-1",
        template=template,
        threshold=0.35,
        mask_scores=False,
    )
    assert is_match is True
    assert sim is not None
    assert abs(sim - 1.0) < 1e-4


def test_near_threshold_anomaly_detector_clustering():
    detector = NearThresholdAnomalyDetector(
        threshold=0.35,
        delta=0.05,
        max_clustering_events=5,
        window_seconds=100.0,
    )

    # 1. Normal requests far from threshold do NOT trigger
    for _ in range(10):
        # High match
        assert detector.check_and_record("dev-01", "user-1", 0.85) is False
        # Clear non-match
        assert detector.check_and_record("dev-01", "user-1", 0.10) is False

    assert detector.stats.total_near_threshold_events == 0

    # 2. Sequential near-threshold attempts: [0.30, 0.40]
    near_scores = [0.34, 0.36, 0.32, 0.38]
    for s in near_scores:
        assert detector.check_and_record("dev-01", "user-1", s) is False

    assert detector.stats.total_near_threshold_events == 4
    assert detector.stats.total_anomalies_flagged == 0

    # 5th attempt in window must trigger anomaly!
    assert detector.check_and_record("dev-01", "user-1", 0.35) is True
    assert detector.stats.total_anomalies_flagged == 1


def test_near_threshold_anomaly_window_expiry():
    detector = NearThresholdAnomalyDetector(
        threshold=0.35,
        delta=0.05,
        max_clustering_events=3,
        window_seconds=10.0,
    )

    now = 1000.0
    # 2 near-threshold events at t=1000.0
    assert detector.check_and_record("dev-01", "user-1", 0.34, timestamp=now) is False
    assert detector.check_and_record("dev-01", "user-1", 0.36, timestamp=now) is False

    # Next attempt happens at t=1015.0 (> 10s window) -> old events expired, only 1 in window
    assert detector.check_and_record("dev-01", "user-1", 0.35, timestamp=now + 15.0) is False
    assert detector.stats.total_anomalies_flagged == 0
