# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
anomaly_detector.py: Near-threshold biometric hill-climbing anomaly detector.

Detects gradient-approximation and black-box hill climbing attacks by tracking
verification attempts clustering within a narrow band around the decision threshold tau +/- delta.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class AnomalyDetectorStats:
    total_near_threshold_events: int = 0
    total_anomalies_flagged: int = 0


class NearThresholdAnomalyDetector:
    """
    Tracks verification similarity scores per device/user identity in a sliding time window.
    Flags repeated attempts landing in [tau - delta, tau + delta] indicative of hill-climbing.
    """

    def __init__(
        self,
        threshold: float = 0.35,
        delta: float = 0.05,
        max_clustering_events: int = 5,
        window_seconds: float = 300.0,
    ) -> None:
        self.threshold = threshold
        self.delta = delta
        self.max_clustering_events = max_clustering_events
        self.window_seconds = window_seconds

        # Key: (device_id, user_id) -> list of timestamps
        self._history: dict[tuple[str, str], list[float]] = defaultdict(list)
        self.stats = AnomalyDetectorStats()

    def check_and_record(
        self,
        device_id: str,
        user_id: str,
        score: float,
        timestamp: float | None = None,
    ) -> bool:
        """
        Records attempt and checks if near-threshold anomaly threshold is breached.
        Returns True if hill-climbing is suspected, False otherwise.
        """
        now = time.time() if timestamp is None else timestamp
        key = (device_id, user_id)

        # Check if score lands in near-threshold danger band [tau - delta, tau + delta]
        lower_bound = self.threshold - self.delta
        upper_bound = self.threshold + self.delta

        if not (lower_bound <= score <= upper_bound):
            return False

        self.stats.total_near_threshold_events += 1

        # Prune expired timestamps in window
        history = self._history[key]
        cutoff = now - self.window_seconds
        valid_ts = [ts for ts in history if ts >= cutoff]
        valid_ts.append(now)
        self._history[key] = valid_ts

        if len(valid_ts) >= self.max_clustering_events:
            self.stats.total_anomalies_flagged += 1
            return True

        return False

    def clear(self) -> None:
        self._history.clear()
        self.stats = AnomalyDetectorStats()
