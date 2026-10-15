# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
base.py: Audit event definitions, score bucketing, and abstract audit sink contract.
"""

from __future__ import annotations

import hashlib
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


def coarse_score_bucket(score: float | None) -> str | None:
    """
    Categorizes raw similarity score into coarse buckets to prevent hill-climbing attacks.
    NEVER logs or persists raw floating-point similarity values in audit records.
    """
    if score is None:
        return None
    if score < 0.20:
        return "very_low"
    if score < 0.35:
        return "low"
    if score < 0.50:
        return "medium"
    if score < 0.70:
        return "high"
    return "very_high"


def hash_client_ip(ip: str | None, salt: str = "freqid_ip_salt") -> str | None:
    """Computes privacy-preserving truncated SHA-256 hash of client network IP."""
    if not ip or ip in ("unknown", "127.0.0.1", "localhost", "testclient"):
        return None
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()[:16]


@dataclass(frozen=True)
class AuditEvent:
    event_type: str  # verify, identify, enroll, re_enroll, delete, rate_limit_block, auth_failure
    principal_type: str  # device, admin, system, anonymous
    decision: str  # match, no_match, error, blocked
    request_id: str
    event_id: uuid.UUID = field(default_factory=uuid.uuid4)
    event_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    principal_id: str | None = None
    device_id: str | None = None
    admin_id: str | None = None
    user_external_id: str | None = None
    score_bucket: str | None = None
    model_version: str | None = None
    client_ip: str | None = None


class AuditSink(ABC):
    """Abstract sink for persistent audit logging."""

    @abstractmethod
    async def emit(self, event: AuditEvent) -> None:
        """Emits an audit event without blocking request execution."""

    @abstractmethod
    async def start(self) -> None:
        """Starts background worker task."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Flushes queue and gracefully shuts down background worker."""
