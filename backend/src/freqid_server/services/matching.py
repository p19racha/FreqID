# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
matching.py: Biometric verification and identification routines with anti-enumeration protection.
"""

from __future__ import annotations

from typing import Any

import freqid_core as fq
import numpy as np
from freqid_core.matching import MatchResult

from freqid_server.errors import ModelVersionMismatchError
from freqid_server.storage.base import EnrolledTemplate


class MatchingService:
    """Coordinates 1:1 verification and 1:N identification scoring and threshold decisions."""

    def __init__(self, active_model_version: str) -> None:
        self.active_model_version = active_model_version
        # Fixed neutral baseline vector for anti-enumeration timing balancing
        self._dummy_reference = np.zeros(512, dtype=np.float32)
        self._dummy_reference[0] = 1.0

    @staticmethod
    def quantize_and_noise_score(
        score: float,
        step: float = 0.05,
        epsilon: float = 2.0,
        rng: np.random.Generator | None = None,
    ) -> float:
        """
        Quantizes similarity score to discrete step increments and adds calibrated Laplace noise.
        Provides differential privacy and breaks fine-grained gradient-based hill-climbing attacks.
        """
        quantized = round(score / step) * step
        scale = step / epsilon
        if rng is not None:
            noise = float(rng.laplace(0.0, scale))
        else:
            u = float(np.random.uniform(-0.4999, 0.4999))
            noise = float(-scale * np.sign(u) * np.log(1.0 - 2.0 * abs(u)))
        noised = max(-1.0, min(1.0, quantized + noise))
        return float(round(noised, 3))

    def verify(
        self,
        query_embedding: np.ndarray,
        claimed_identity: str,
        template: EnrolledTemplate | None,
        threshold: float = 0.35,
        mask_scores: bool = False,
        apply_noise: bool = False,
    ) -> tuple[bool, float | None]:
        """
        Executes 1:1 biometric verification against claimed identity template.

        ANTI-ENUMERATION MITIGATION:
        If claimed_identity is not found, executes a dummy cosine similarity against a
        neutral reference to balance CPU timing before returning False.
        """
        if template is None:
            # Dummy computation to prevent timing side-channel
            _ = float(fq.cosine_similarity(query_embedding, self._dummy_reference))
            score_out = None if mask_scores else -0.1
            return False, score_out

        # Enforce model version parity
        if template.model_version != self.active_model_version:
            raise ModelVersionMismatchError(
                f"Stored template for user '{claimed_identity}' was produced with model version "
                f"'{template.model_version}', but server is running '{self.active_model_version}'. "
                f"Re-enrollment is required."
            )

        score, is_match = fq.verify(
            embedding_a=query_embedding,
            embedding_b=template.embedding,
            threshold=threshold,
        )

        if mask_scores:
            score_out = None
        elif apply_noise:
            score_out = self.quantize_and_noise_score(float(score))
        else:
            score_out = float(score)

        return bool(is_match), score_out

    def format_candidates(
        self,
        results: list[MatchResult],
        mask_scores: bool = False,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Formats 1:N match candidates, applying score masking if configured."""
        candidates: list[dict[str, Any]] = []
        for r in results:
            candidates.append(
                {
                    "user_id": r.target_id,
                    "similarity": None if mask_scores else float(r.similarity),
                    "rank": r.rank,
                    "is_match": r.is_match,
                }
            )

        top_candidate = None
        if candidates and candidates[0]["is_match"]:
            top_candidate = candidates[0]

        return top_candidate, candidates
