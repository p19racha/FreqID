# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_security.py: Security validation, spatial image rejection, replay protection, rate limits, and scopes.
"""

from __future__ import annotations

import secrets

import httpx
import pytest


@pytest.mark.asyncio
async def test_image_data_rejection_hard_rule_3(
    client: httpx.AsyncClient,
    sample_payload_bytes: bytes,
):
    """Proves that spatial images (JPEG, PNG, BMP) are strictly rejected."""
    headers = {
        "Content-Type": "application/vnd.freqid.payload",
        "X-Device-ID": "test-device",
        "X-Claimed-Identity": "alice",
        "X-Nonce": secrets.token_hex(16),
        "Authorization": "Bearer dev_verify_token",
    }

    # 1. Reject image/jpeg Content-Type
    img_type_headers = dict(headers)
    img_type_headers["Content-Type"] = "image/jpeg"
    res1 = await client.post("/v1/verify", headers=img_type_headers, content=b"fake jpeg content")
    assert res1.status_code == 415

    # 2. Reject JPEG magic bytes (SOI marker \xff\xd8\xff)
    jpeg_body = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    headers["X-Nonce"] = secrets.token_hex(16)
    res2 = await client.post("/v1/verify", headers=headers, content=jpeg_body)
    assert res2.status_code == 400
    assert res2.json()["error"]["code"] == "IMAGE_DATA_REJECTED"

    # 3. Reject PNG magic bytes (\x89PNG\r\n\x1a\n)
    png_body = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    headers["X-Nonce"] = secrets.token_hex(16)
    res3 = await client.post("/v1/verify", headers=headers, content=png_body)
    assert res3.status_code == 400
    assert res3.json()["error"]["code"] == "IMAGE_DATA_REJECTED"

    # 4. Reject BMP magic bytes (BM)
    bmp_body = b"BM" + b"\x00" * 100
    headers["X-Nonce"] = secrets.token_hex(16)
    res4 = await client.post("/v1/verify", headers=headers, content=bmp_body)
    assert res4.status_code == 400
    assert res4.json()["error"]["code"] == "IMAGE_DATA_REJECTED"


@pytest.mark.asyncio
async def test_payload_size_limit(client: httpx.AsyncClient):
    """Rejects request bodies exceeding maximum payload size limit."""
    headers = {
        "Content-Type": "application/vnd.freqid.payload",
        "X-Device-ID": "test-device",
        "X-Claimed-Identity": "alice",
        "X-Nonce": secrets.token_hex(16),
        "Authorization": "Bearer dev_verify_token",
    }
    # 3 MB body exceeds 2 MB default limit
    oversized_body = b"\x00" * (3 * 1024 * 1024)
    res = await client.post("/v1/verify", headers=headers, content=oversized_body)
    assert res.status_code == 413
    assert res.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


@pytest.mark.asyncio
async def test_replay_attack_prevention(
    client: httpx.AsyncClient,
    sample_payload_bytes: bytes,
):
    """Proves that a duplicate X-Nonce is rejected with 400 REPLAY_DETECTED."""
    nonce = secrets.token_hex(16)
    headers = {
        "Content-Type": "application/vnd.freqid.payload",
        "X-Device-ID": "test-device",
        "X-Claimed-Identity": "alice",
        "X-Nonce": nonce,
        "Authorization": "Bearer dev_verify_token",
    }

    # First request: consumed nonce
    res1 = await client.post("/v1/verify", headers=headers, content=sample_payload_bytes)
    assert res1.status_code == 200

    # Second request: replay of the exact same nonce
    res2 = await client.post("/v1/verify", headers=headers, content=sample_payload_bytes)
    assert res2.status_code == 400
    assert res2.json()["error"]["code"] == "REPLAY_DETECTED"


@pytest.mark.asyncio
async def test_authentication_and_scope_enforcement(
    client: httpx.AsyncClient,
    sample_payload_bytes: bytes,
):
    """Enforces constant-time static token verification and endpoint permission scopes."""
    # 1. Missing Authorization header
    headers = {
        "Content-Type": "application/vnd.freqid.payload",
        "X-Device-ID": "test-device",
        "X-Claimed-Identity": "alice",
        "X-Nonce": secrets.token_hex(16),
    }
    res_no_auth = await client.post("/v1/verify", headers=headers, content=sample_payload_bytes)
    assert res_no_auth.status_code == 401

    # 2. Invalid bearer token
    headers["Authorization"] = "Bearer wrong_token_value"
    headers["X-Nonce"] = secrets.token_hex(16)
    res_bad_auth = await client.post("/v1/verify", headers=headers, content=sample_payload_bytes)
    assert res_bad_auth.status_code == 401

    # 3. Insufficient scope: 'verify' token cannot call 'enroll'
    enroll_headers = {
        "Content-Type": "application/vnd.freqid.payload",
        "X-Device-ID": "test-device",
        "X-User-ID": "alice",
        "Authorization": "Bearer dev_verify_token",
    }
    res_enroll_scope = await client.post("/v1/enroll", headers=enroll_headers, content=sample_payload_bytes)
    assert res_enroll_scope.status_code == 403
    assert res_enroll_scope.json()["error"]["code"] == "INSUFFICIENT_SCOPE"

    # 4. Insufficient scope: 'kiosk' token cannot call 'delete user'
    res_del_scope = await client.delete("/v1/users/alice", headers={"Authorization": "Bearer dev_kiosk_token"})
    assert res_del_scope.status_code == 403


@pytest.mark.asyncio
async def test_failed_verification_lockout(
    client: httpx.AsyncClient,
    sample_payload_bytes: bytes,
):
    """Verifies that consecutive failed verifications lock out the claimed user identity."""
    target_user = "lockout_victim"
    # Max failed attempts is configured to 3 in test_config
    for _ in range(3):
        headers = {
            "Content-Type": "application/vnd.freqid.payload",
            "X-Device-ID": "attacker-device",
            "X-Claimed-Identity": target_user,
            "X-Nonce": secrets.token_hex(16),
            "Authorization": "Bearer dev_verify_token",
        }
        res = await client.post("/v1/verify", headers=headers, content=sample_payload_bytes)
        assert res.status_code == 200
        assert res.json()["is_match"] is False

    # 4th attempt must be rejected with 429 RATE_LIMIT_EXCEEDED
    headers["X-Nonce"] = secrets.token_hex(16)
    res_locked = await client.post("/v1/verify", headers=headers, content=sample_payload_bytes)
    assert res_locked.status_code == 429
    assert res_locked.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in res_locked.headers
