# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_log_redaction.py: Biometric data redaction audit (Hard Rule 4).

Proves that server logs never contain floating-point embedding vectors,
raw payload bytes, or similarity arrays.
"""

from __future__ import annotations

import io
import logging
import re
import secrets

import httpx
import numpy as np
import pytest

from freqid_server.logging import BiometricRedactionFilter, logger


@pytest.mark.asyncio
async def test_log_redaction_during_operations(
    client: httpx.AsyncClient,
    sample_payload_bytes: bytes,
):
    """Captures all server logs during verify and enroll, verifying no biometric data leakage."""
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setLevel(logging.DEBUG)
    handler.addFilter(BiometricRedactionFilter())
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger.addHandler(handler)
    try:
        # 1. Execute enrollment
        enroll_headers = {
            "Content-Type": "application/vnd.freqid.payload",
            "X-Device-ID": "audit-device",
            "X-User-ID": "audit_user",
            "Authorization": "Bearer dev_admin_token",
        }
        res_enroll = await client.post(
            "/v1/enroll", headers=enroll_headers, content=sample_payload_bytes
        )
        assert res_enroll.status_code == 201

        # 2. Execute verification
        verify_headers = {
            "Content-Type": "application/vnd.freqid.payload",
            "X-Device-ID": "audit-device",
            "X-Claimed-Identity": "audit_user",
            "X-Nonce": secrets.token_hex(16),
            "Authorization": "Bearer dev_verify_token",
        }
        res_verify = await client.post(
            "/v1/verify", headers=verify_headers, content=sample_payload_bytes
        )
        assert res_verify.status_code == 200

        # 3. Simulate accidental direct attempt to log raw float embedding array
        accidental_emb = np.random.randn(512).astype(np.float32).tolist()
        logger.info(f"Testing filter against accidental leak: {accidental_emb}")

        # 4. Simulate accidental direct attempt to log raw binary payload bytes
        accidental_bytes = (
            b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13"
        )
        logger.info(f"Testing filter against binary leak: {accidental_bytes!r}")

        log_content = log_stream.getvalue()

        # AUDIT HARD RULE 4:
        # A) No raw float vector of 4+ elements should exist
        float_vector_pattern = re.compile(r"\[(?:\s*-?\d+\.\d+[\s,]*){4,}\]")
        leakage = float_vector_pattern.findall(log_content)
        assert len(leakage) == 0, f"Biometric float vector leaked in logs: {leakage}"

        # B) Redaction markers must be present for the intercepted leak attempts
        assert "[REDACTED_BIOMETRIC_VECTOR]" in log_content
        assert "[REDACTED_BINARY_PAYLOAD]" in log_content

        # C) Standard diagnostic fields are retained
        assert "POST /v1/enroll HTTP 201" in log_content
        assert "POST /v1/verify HTTP 200" in log_content
        assert "req_id:" in log_content

    finally:
        logger.removeHandler(handler)
