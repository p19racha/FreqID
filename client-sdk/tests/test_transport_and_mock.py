# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_transport_and_mock.py: Integration tests connecting FreqIDTransport to the FastAPI mock server.
"""

import freqid_core as fq
import numpy as np
import pytest
from starlette.testclient import TestClient

from freqid_client.auth import NoAuth
from freqid_client.errors import ServerRejectedError
from freqid_client.mock_server.app import app
from freqid_client.transport import FreqIDTransport


@pytest.fixture
def test_transport(monkeypatch):
    """Creates a FreqIDTransport wired directly into the mock server via TestClient."""
    transport = FreqIDTransport(
        server_url="http://testserver",
        device_id="test_device_01",
        auth=NoAuth(),
    )
    # Patch internal httpx client to talk directly to FastAPI app in memory
    transport._client = TestClient(app, base_url="http://testserver")
    yield transport
    transport.close()


def test_mock_health(test_transport):
    r = test_transport._client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_enroll_and_verify_end_to_end(test_transport):
    from pathlib import Path

    import cv2
    from freqid_core.transform import image_to_partial_frequency

    img_dir = Path("data/train_subset/images")
    img_alice1_path = img_dir / "id_0053" / "img_00.png"
    img_alice2_path = img_dir / "id_0053" / "img_01.png"
    img_bob_path = img_dir / "id_0001" / "img_00.png"

    if img_alice1_path.exists() and img_bob_path.exists():
        im_a1 = cv2.imread(str(img_alice1_path))
        im_a2 = cv2.imread(str(img_alice2_path))
        im_b = cv2.imread(str(img_bob_path))
        f_a1 = image_to_partial_frequency(
            cv2.cvtColor(im_a1, cv2.COLOR_BGR2RGB), subset_index=0, perm_index=0, engine="numpy"
        )
        f_a2 = image_to_partial_frequency(
            cv2.cvtColor(im_a2, cv2.COLOR_BGR2RGB), subset_index=0, perm_index=0, engine="numpy"
        )
        f_b = image_to_partial_frequency(
            cv2.cvtColor(im_b, cv2.COLOR_BGR2RGB), subset_index=0, perm_index=0, engine="numpy"
        )
        p_alice1 = fq.PartialFacePayload(f_a1, subset_index=0, perm_index=0).to_bytes()
        p_alice2 = fq.PartialFacePayload(f_a2, subset_index=0, perm_index=0).to_bytes()
        p_bob = fq.PartialFacePayload(f_b, subset_index=0, perm_index=0).to_bytes()
    else:
        np.random.seed(101)
        data_alice1 = np.random.randn(27, 112, 112).astype(np.float32)
        data_alice2 = data_alice1 + np.random.normal(0, 0.01, (27, 112, 112)).astype(np.float32)
        data_bob = -data_alice1
        p_alice1 = fq.PartialFacePayload(data_alice1, subset_index=0, perm_index=0).to_bytes()
        p_alice2 = fq.PartialFacePayload(data_alice2, subset_index=0, perm_index=0).to_bytes()
        p_bob = fq.PartialFacePayload(data_bob, subset_index=0, perm_index=0).to_bytes()

    # 1. Enroll Alice
    enroll_res = test_transport.enroll(payload_bytes_list=[p_alice1], user_id="alice")
    assert enroll_res["status"] == "enrolled"
    assert enroll_res["user_id"] == "alice"

    # 2. Verify Alice (Photo 2) against Alice -> Should Match
    ver_alice = test_transport.verify(payload_bytes=p_alice2, claimed_identity="alice")
    assert ver_alice["status"] == "success"
    assert ver_alice["is_match"] is True
    assert ver_alice["similarity"] > 0.35

    # 3. Verify Bob against Alice -> Should Reject
    ver_bob = test_transport.verify(payload_bytes=p_bob, claimed_identity="alice")
    assert ver_bob["status"] == "success"
    assert ver_bob["is_match"] is False
    assert ver_bob["similarity"] < 0.35


def test_replay_attack_rejected(test_transport):
    dummy_payload = fq.PartialFacePayload(
        np.random.randn(27, 112, 112).astype(np.float32)
    ).to_bytes()
    fixed_nonce = "fixed_test_nonce_1234"

    # First request: succeeds
    res1 = test_transport.verify(
        payload_bytes=dummy_payload,
        claimed_identity="user_x",
        nonce=fixed_nonce,
    )
    assert res1["status"] == "success"

    # Second request with same nonce: rejected with REPLAY_DETECTED
    with pytest.raises(ServerRejectedError) as exc_info:
        test_transport.verify(
            payload_bytes=dummy_payload,
            claimed_identity="user_x",
            nonce=fixed_nonce,
        )
    assert exc_info.value.error_code == "REPLAY_DETECTED"


def test_corrupted_payload_rejected(test_transport):
    corrupted_bytes = b"BAD_PAYLOAD_CORRUPTED_BYTES"
    with pytest.raises(ServerRejectedError) as exc_info:
        test_transport.verify(payload_bytes=corrupted_bytes, claimed_identity="alice")
    assert exc_info.value.error_code == "INVALID_PAYLOAD"
