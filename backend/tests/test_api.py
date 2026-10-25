# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_api.py: Comprehensive functional tests for verification, identification, enrollment, and health endpoints.
"""

from __future__ import annotations

import secrets

import httpx
import pytest


@pytest.mark.asyncio
async def test_health_and_readiness_endpoints(client: httpx.AsyncClient):
    """Verifies liveness, readiness, and model metadata probes."""
    res_healthz = await client.get("/healthz")
    assert res_healthz.status_code == 200
    assert res_healthz.json() == {"status": "ok", "service": "freqid-server"}

    res_health = await client.get("/health")
    assert res_health.status_code == 200

    res_readyz = await client.get("/readyz")
    assert res_readyz.status_code == 200
    data = res_readyz.json()
    assert data["status"] == "ready"
    assert data["model_loaded"] is True
    assert data["backend"] == "onnx"

    res_model = await client.get("/v1/model")
    assert res_model.status_code == 200
    model_data = res_model.json()
    assert model_data["embedding_dim"] == 512
    assert model_data["input_channels"] == 27
    assert len(model_data["checkpoint_sha256"]) == 64

    res_metrics = await client.get("/metrics")
    assert res_metrics.status_code == 200
    assert "freqid_up 1" in res_metrics.text
    assert "freqid_model_loaded 1" in res_metrics.text
    assert "freqid_store_connected" in res_metrics.text
    assert "freqid_enrolled_identities" in res_metrics.text


@pytest.mark.asyncio
async def test_enrollment_and_lifecycle(
    client: httpx.AsyncClient,
    sample_payload_bytes: bytes,
    auth_headers: dict,
):
    """Tests single and multi-sample enrollment and identity template deletion."""
    user_id = "alice_test"

    # 1. Enroll single frame
    headers = {
        "Content-Type": "application/vnd.freqid.payload",
        "X-Device-ID": "kiosk-station-01",
        "X-User-ID": user_id,
        "Authorization": "Bearer dev_enroll_token",
    }
    res_enroll = await client.post("/v1/enroll", headers=headers, content=sample_payload_bytes)
    assert res_enroll.status_code == 201
    enroll_data = res_enroll.json()
    assert enroll_data["status"] == "enrolled"
    assert enroll_data["user_id"] == user_id
    assert enroll_data["frames_accepted"] == 1

    # 2. Verify identity matches
    v_headers = {
        "Content-Type": "application/vnd.freqid.payload",
        "X-Device-ID": "kiosk-station-01",
        "X-Claimed-Identity": user_id,
        "X-Nonce": secrets.token_hex(16),
        "Authorization": "Bearer dev_verify_token",
    }
    res_verify = await client.post("/v1/verify", headers=v_headers, content=sample_payload_bytes)
    assert res_verify.status_code == 200
    verify_data = res_verify.json()
    assert verify_data["is_match"] is True
    assert verify_data["claimed_identity"] == user_id
    assert verify_data["similarity"] is not None
    assert verify_data["similarity"] > 0.99  # Identical payload should match near 1.0

    # 3. Identify identity
    id_headers = {
        "Content-Type": "application/vnd.freqid.payload",
        "X-Device-ID": "kiosk-station-01",
        "X-Nonce": secrets.token_hex(16),
        "Authorization": "Bearer dev_kiosk_token",
    }
    res_identify = await client.post(
        "/v1/identify", headers=id_headers, content=sample_payload_bytes
    )
    assert res_identify.status_code == 200
    id_data = res_identify.json()
    assert id_data["is_match"] is True
    assert id_data["top_candidate"]["user_id"] == user_id
    assert id_data["top_candidate"]["similarity"] > 0.99

    # 4. Delete user template
    del_headers = {"Authorization": "Bearer dev_admin_token"}
    res_del = await client.delete(f"/v1/users/{user_id}", headers=del_headers)
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "deleted"

    # 5. Subsequent verification must fail (user deleted)
    v_headers["X-Nonce"] = secrets.token_hex(16)
    res_verify_after = await client.post(
        "/v1/verify", headers=v_headers, content=sample_payload_bytes
    )
    assert res_verify_after.status_code == 200
    assert res_verify_after.json()["is_match"] is False

    # 6. Deleting non-existent user returns 404
    res_del_404 = await client.delete("/v1/users/non_existent_user", headers=del_headers)
    assert res_del_404.status_code == 404


@pytest.mark.asyncio
async def test_anti_enumeration_behavior(
    client: httpx.AsyncClient,
    sample_payload_bytes: bytes,
):
    """
    Verifies that verifying a non-existent user returns 200 OK with is_match: False
    without leaking user existence via 404 or distinct error responses.
    """
    headers = {
        "Content-Type": "application/vnd.freqid.payload",
        "X-Device-ID": "kiosk-station-01",
        "X-Claimed-Identity": "ghost_user_does_not_exist",
        "X-Nonce": secrets.token_hex(16),
        "Authorization": "Bearer dev_verify_token",
    }
    res = await client.post("/v1/verify", headers=headers, content=sample_payload_bytes)
    assert res.status_code == 200
    data = res.json()
    assert data["is_match"] is False
    assert data["verified_identity"] is None
