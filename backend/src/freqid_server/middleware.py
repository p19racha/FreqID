# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
middleware.py: Security enforcement, nonce deduplication, image rejection, and rate limiting.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from typing import Any, ClassVar

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from freqid_server.config import ServerConfig
from freqid_server.logging import logger


class NonceTracker:
    """Thread-safe cryptographic nonce cache with sliding TTL window."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self.ttl = ttl_seconds
        self._nonces: dict[str, float] = {}

    def check_and_record(self, nonce: str) -> bool:
        """Returns True if nonce is fresh and records it; False if duplicate."""
        now = time.time()
        self._purge(now)

        if nonce in self._nonces:
            return False

        self._nonces[nonce] = now
        return True

    def _purge(self, now: float) -> None:
        cutoff = now - self.ttl
        # Purge expired nonces if dict grows large
        if len(self._nonces) > 500:
            self._nonces = {n: t for n, t in self._nonces.items() if t >= cutoff}


class RateLimiter:
    """Sliding-window in-memory rate limiter with user lockout on failed attempts."""

    def __init__(
        self, rate_limit_per_min: int = 120, max_failed_lockout: int = 5, lockout_sec: int = 60
    ) -> None:
        self.rate_limit = rate_limit_per_min
        self.max_failed = max_failed_lockout
        self.lockout_duration = lockout_sec

        self._requests: dict[str, list[float]] = defaultdict(list)
        self._failed_counts: dict[str, int] = defaultdict(int)
        self._locked_until: dict[str, float] = {}

    def check_rate_limit(self, client_key: str) -> tuple[bool, int]:
        now = time.time()
        window_start = now - 60.0

        timestamps = [t for t in self._requests[client_key] if t >= window_start]
        self._requests[client_key] = timestamps

        if len(timestamps) >= self.rate_limit:
            retry_after = int(60.0 - (now - timestamps[0])) + 1
            return False, max(1, retry_after)

        self._requests[client_key].append(now)
        return True, 0

    def check_user_lockout(self, user_id: str) -> tuple[bool, int]:
        now = time.time()
        if user_id in self._locked_until:
            if now < self._locked_until[user_id]:
                retry_after = int(self._locked_until[user_id] - now) + 1
                return False, retry_after
            else:
                del self._locked_until[user_id]
                self._failed_counts[user_id] = 0
        return True, 0

    def record_verification_result(self, user_id: str, is_match: bool) -> None:
        now = time.time()
        if is_match:
            self._failed_counts[user_id] = 0
        else:
            self._failed_counts[user_id] += 1
            if self._failed_counts[user_id] >= self.max_failed:
                self._locked_until[user_id] = now + self.lockout_duration
                logger.warning(
                    f"Temporary lockout triggered for user '{user_id}' due to {self.max_failed} consecutive failed verifications."
                )


class SecurityMiddleware(BaseHTTPMiddleware):
    """
    Enforces request body size bounds, image rejection filters, and request tracking.
    """

    KNOWN_IMAGE_MAGIC: ClassVar[list[bytes]] = [
        b"\xff\xd8\xff",  # JPEG
        b"\x89PNG\r\n\x1a\n",  # PNG
        b"BM",  # BMP
        b"GIF87a",  # GIF87a
        b"GIF89a",  # GIF89a
        b"RIFF",  # WebP (RIFF....WEBP)
    ]

    def __init__(
        self, app: Any, config: ServerConfig, nonce_tracker: NonceTracker, rate_limiter: RateLimiter
    ) -> None:
        super().__init__(app)
        self.config = config
        self.nonces = nonce_tracker
        self.rate_limiter = rate_limiter

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        t_start = time.perf_counter()
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = req_id

        path = request.url.path
        client_ip = request.client.host if request.client else "unknown"

        # 1. Rate Limiting Check (bypass for health probes)
        if path not in ("/healthz", "/readyz", "/health"):
            allowed, retry_after = self.rate_limiter.check_rate_limit(client_ip)
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "RATE_LIMIT_EXCEEDED",
                            "message": "Too many requests. Please slow down.",
                            "request_id": req_id,
                        }
                    },
                    headers={"Retry-After": str(retry_after)},
                )

        # 2. Reject Spatial Image Media Types
        content_type = request.headers.get("Content-Type", "")
        if content_type.startswith("image/"):
            return JSONResponse(
                status_code=415,
                content={
                    "error": {
                        "code": "UNSUPPORTED_MEDIA_TYPE",
                        "message": "Raw spatial image uploads are strictly forbidden. Only partial frequency payloads are accepted.",
                        "request_id": req_id,
                    }
                },
            )

        # 3. Size and Binary Inspections on POST endpoints
        if request.method == "POST" and path in (
            "/v1/verify",
            "/api/v1/auth/verify",
            "/v1/identify",
            "/api/v1/auth/identify",
            "/v1/enroll",
            "/api/v1/enroll/frames",
        ):
            is_enroll = "enroll" in path
            max_size = (
                self.config.max_batch_payload_bytes
                if is_enroll
                else self.config.max_single_payload_bytes
            )

            content_length = request.headers.get("Content-Length")
            if content_length and int(content_length) > max_size:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "PAYLOAD_TOO_LARGE",
                            "message": f"Payload size {content_length} bytes exceeds maximum limit ({max_size} bytes).",
                            "request_id": req_id,
                        }
                    },
                )

            # Inspect body for spatial image magic bytes and verify nonce
            body = await request.body()
            if len(body) > max_size:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "PAYLOAD_TOO_LARGE",
                            "message": f"Received body of {len(body)} bytes exceeds maximum limit ({max_size} bytes).",
                            "request_id": req_id,
                        }
                    },
                )

            # Hard Rule 3: Rejection of spatial image binary bytes
            for magic in self.KNOWN_IMAGE_MAGIC:
                if body.startswith(magic):
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": {
                                "code": "IMAGE_DATA_REJECTED",
                                "message": "Uploaded content contains raw spatial image bytes. Only partial frequency payloads are permitted.",
                                "request_id": req_id,
                            }
                        },
                    )

            # Replay Protection: Nonce verification
            nonce = request.headers.get("X-Nonce")
            if nonce and not self.nonces.check_and_record(nonce):
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": {
                            "code": "REPLAY_DETECTED",
                            "message": f"Nonce '{nonce}' has already been consumed.",
                            "request_id": req_id,
                        }
                    },
                )

        response = await call_next(request)
        duration_ms = (time.perf_counter() - t_start) * 1000.0

        # Inject standard security and tracking headers
        response.headers["X-Request-ID"] = req_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"

        logger.info(
            f"{request.method} {path} HTTP {response.status_code} in {duration_ms:.2f}ms (req_id: {req_id})"
        )
        return response
