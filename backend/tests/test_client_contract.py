# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_client_contract.py: End-to-end integration test with the real Phase 3 freqid-client SDK.
"""

from __future__ import annotations

import socket
import threading
import time

import freqid_core as fq
import numpy as np
import pytest
import uvicorn
from freqid_client.auth import StaticTokenAuthenticator as ClientStaticTokenAuth
from freqid_client.transport import FreqIDTransport

from freqid_server.config import ServerConfig
from freqid_server.main import create_app
from freqid_server.storage.memory import MemoryTemplateStore


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server_url():
    port = get_free_port()
    cfg = ServerConfig(
        host="127.0.0.1",
        port=port,
        environment="test",
        model_path="research/outputs/checkpoints/partialface_ir_18.onnx",
        model_backend="onnx",
        device="cpu",
        mask_scores_in_production=False,
        static_tokens={
            "client_test_token": ["verify", "identify", "enroll", "admin"],
        },
    )

    app = create_app(config=cfg, store=MemoryTemplateStore())
    app.state.inference.start()

    server_config = uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="warning", loop="asyncio")
    server = uvicorn.Server(server_config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to come up
    url = f"http://127.0.0.1:{port}"
    timeout = time.time() + 5.0
    connected = False
    import httpx

    while time.time() < timeout:
        try:
            r = httpx.get(f"{url}/healthz", timeout=0.5)
            if r.status_code == 200:
                connected = True
                break
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            time.sleep(0.05)

    assert connected, "Live test server failed to start within 5 seconds."

    yield url

    server.should_exit = True
    thread.join(timeout=3.0)
    app.state.inference.shutdown()


def test_client_transport_e2e(live_server_url: str):
    """
    Executes real network requests using freqid_client.transport.FreqIDTransport
    against the running freqid-server.
    """
    auth = ClientStaticTokenAuth(token="client_test_token")
    transport = FreqIDTransport(
        server_url=live_server_url,
        device_id="client-kiosk-e2e",
        auth=auth,
        insecure_skip_verify=True,
    )

    rng = np.random.RandomState(999)
    # Generate 3 similar payloads (perturbed slightly to test multi-sample averaging)
    base_data = rng.randn(27, 112, 112).astype(np.float32)
    payload1 = fq.PartialFacePayload(data=base_data)
    payload2 = fq.PartialFacePayload(data=base_data + rng.randn(27, 112, 112).astype(np.float32) * 0.01)
    payload3 = fq.PartialFacePayload(data=base_data + rng.randn(27, 112, 112).astype(np.float32) * 0.01)

    payload_bytes_list = [payload1.to_bytes(), payload2.to_bytes(), payload3.to_bytes()]
    user_id = "test_e2e_user"

    # 1. Enroll user using real client SDK transport
    enroll_resp = transport.enroll(
        payload_bytes_list=payload_bytes_list,
        user_id=user_id,
    )
    assert enroll_resp["status"] == "enrolled"
    assert enroll_resp["user_id"] == user_id
    assert enroll_resp["frames_processed"] == 3
    assert enroll_resp["frames_accepted"] == 3

    # 2. Verify user using real client SDK transport
    verify_resp = transport.verify(
        payload_bytes=payload1.to_bytes(),
        claimed_identity=user_id,
    )
    assert verify_resp["status"] == "success"
    assert verify_resp["is_match"] is True
    assert verify_resp["claimed_identity"] == user_id
    assert verify_resp["similarity"] > 0.95

    # 3. Identify user using real client SDK transport
    identify_resp = transport.identify(
        payload_bytes=payload1.to_bytes(),
        top_k=3,
    )
    assert identify_resp["status"] == "success"
    assert identify_resp["is_match"] is True
    assert identify_resp["top_candidate"] is not None
    assert identify_resp["top_candidate"]["user_id"] == user_id
    assert identify_resp["top_candidate"]["similarity"] > 0.95

    transport.close()


def test_client_postgres_persistence_across_server_restart():
    """
    Proves persistent storage across server lifecycles:
    1. Starts Server 1 with PostgreSQL storage backend.
    2. Client enrolls user via real FreqIDTransport.
    3. Server 1 terminates.
    4. Server 2 starts on the same PostgreSQL database, restoring in-memory gallery.
    5. Client verifies against Server 2; matching succeeds.
    """
    import asyncio
    import os

    import httpx
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    dev_db_url = os.environ.get(
        "FREQID_TEST_DB_URL",
        "postgresql+asyncpg://freqid_app:freqid_app_dev_secret@127.0.0.1:54322/freqid",
    )
    admin_db_url = os.environ.get(
        "FREQID_TEST_ADMIN_DB_URL",
        "postgresql+asyncpg://freqid_admin:freqid_admin_dev_password@127.0.0.1:54322/freqid",
    )

    # Clean DB
    async def clean_db():
        eng = create_async_engine(admin_db_url, echo=False)
        async with eng.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE audit_events, templates, enrollment_sessions, users CASCADE;"))
        await eng.dispose()

    asyncio.run(clean_db())

    # --- Server 1 ---
    port1 = get_free_port()
    cfg1 = ServerConfig(
        host="127.0.0.1",
        port=port1,
        environment="test",
        storage_backend="postgres",
        database_url=dev_db_url,
        model_path="research/outputs/checkpoints/partialface_ir_18.onnx",
        model_backend="onnx",
        device="cpu",
        mask_scores_in_production=False,
        static_tokens={"client_token": ["verify", "identify", "enroll", "admin"]},
    )
    app1 = create_app(config=cfg1)

    server1_config = uvicorn.Config(app=app1, host="127.0.0.1", port=port1, log_level="warning")
    server1 = uvicorn.Server(server1_config)
    t1 = threading.Thread(target=server1.run, daemon=True)
    t1.start()

    # Wait for server 1
    timeout = time.time() + 5.0
    while time.time() < timeout:
        try:
            r = httpx.get(f"http://127.0.0.1:{port1}/healthz", timeout=0.5)
            if r.status_code == 200:
                break
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            time.sleep(0.05)

    auth = ClientStaticTokenAuth(token="client_token")
    transport1 = FreqIDTransport(
        server_url=f"http://127.0.0.1:{port1}",
        device_id="cam-restart-1",
        auth=auth,
        insecure_skip_verify=True,
    )

    rng = np.random.RandomState(777)
    face_data = rng.randn(27, 112, 112).astype(np.float32)
    p = fq.PartialFacePayload(data=face_data)

    enroll_resp = transport1.enroll(
        payload_bytes_list=[p.to_bytes()],
        user_id="user_restart_survivor",
    )
    assert enroll_resp["status"] == "enrolled"
    transport1.close()

    # Shut down Server 1
    server1.should_exit = True
    t1.join(timeout=3.0)

    # --- Server 2 (Fresh process on same database) ---
    port2 = get_free_port()
    cfg2 = ServerConfig(
        host="127.0.0.1",
        port=port2,
        environment="test",
        storage_backend="postgres",
        database_url=dev_db_url,
        model_path="research/outputs/checkpoints/partialface_ir_18.onnx",
        model_backend="onnx",
        device="cpu",
        mask_scores_in_production=False,
        static_tokens={"client_token": ["verify", "identify", "enroll", "admin"]},
    )
    app2 = create_app(config=cfg2)

    server2_config = uvicorn.Config(app=app2, host="127.0.0.1", port=port2, log_level="warning")
    server2 = uvicorn.Server(server2_config)
    t2 = threading.Thread(target=server2.run, daemon=True)
    t2.start()

    # Wait for server 2
    timeout = time.time() + 5.0
    while time.time() < timeout:
        try:
            r = httpx.get(f"http://127.0.0.1:{port2}/healthz", timeout=0.5)
            if r.status_code == 200:
                break
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            time.sleep(0.05)

    # Client verifies against Server 2
    transport2 = FreqIDTransport(
        server_url=f"http://127.0.0.1:{port2}",
        device_id="cam-restart-2",
        auth=auth,
        insecure_skip_verify=True,
    )

    verify_resp = transport2.verify(
        payload_bytes=p.to_bytes(),
        claimed_identity="user_restart_survivor",
    )
    assert verify_resp["status"] == "success"
    assert verify_resp["is_match"] is True
    assert verify_resp["claimed_identity"] == "user_restart_survivor"
    assert verify_resp["similarity"] > 0.95

    transport2.close()
    server2.should_exit = True
    t2.join(timeout=3.0)

