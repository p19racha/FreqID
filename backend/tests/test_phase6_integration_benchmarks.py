# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_phase6_integration_benchmarks.py: Real client E2E integration, authentication overhead profiling,
and concurrency load benchmarking using a live HTTP server.
"""

from __future__ import annotations

import base64
import concurrent.futures
import json
import os
import secrets
import socket
import stat
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import freqid_core as fq
import httpx
import numpy as np
import pytest
import uvicorn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from freqid_client.auth import DeviceSignatureAuthenticator, pair_device
from freqid_client.transport import FreqIDTransport
from freqid_server.audit.postgres import PostgresAuditSink
from freqid_server.auth.passwords import hash_password
from freqid_server.auth.tokens import create_access_token
from freqid_server.config import ServerConfig
from freqid_server.crypto.envelope import TemplateEncryptor
from freqid_server.crypto.provider import EnvOrFileKeyProvider
from freqid_server.main import create_app
from freqid_server.storage.models import AdminUserOrm
from freqid_server.storage.postgres import PostgreSQLTemplateStore

DEV_DB_URL = os.environ.get(
    "FREQID_TEST_DB_URL",
    "postgresql+asyncpg://freqid_app:freqid_app_dev_secret@127.0.0.1:54322/freqid",
)
ADMIN_DB_URL = os.environ.get(
    "FREQID_TEST_ADMIN_DB_URL",
    "postgresql+asyncpg://freqid_admin:freqid_admin_dev_password@127.0.0.1:54322/freqid",
)
TEST_MASTER_KEY = b"01234567890123456789012345678901"


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server():
    """Starts a live FreqID server instance on a background thread with real PostgreSQL persistence."""
    # Clean DB
    import asyncio
    async def truncate():
        admin_engine = create_async_engine(ADMIN_DB_URL, echo=False)
        async with admin_engine.begin() as conn:
            await conn.execute(text(
                "TRUNCATE TABLE audit_events, templates, enrollment_sessions, users, "
                "device_heartbeats, devices, pairing_tokens, admin_refresh_tokens, "
                "admin_users, system_settings CASCADE;"
            ))
        await admin_engine.dispose()
    asyncio.run(truncate())

    port = get_free_port()
    cfg = ServerConfig(
        host="127.0.0.1",
        port=port,
        environment="test",
        model_path="research/outputs/checkpoints/partialface_ir_18.onnx",
        model_backend="onnx",
        model_version="v1.0-ir18",
        device="cpu",
        decision_threshold=0.35,
        mask_scores_in_production=False,
        storage_backend="postgres",
        database_url=DEV_DB_URL,
        master_key=base64.b64encode(TEST_MASTER_KEY).decode("ascii"),
    )

    app = create_app(config=cfg)

    # Seed Admin User in PostgreSQL
    admin_id = uuid.uuid4()
    async def seed():
        engine = create_async_engine(DEV_DB_URL, echo=False)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            adm = AdminUserOrm(
                id=admin_id,
                username="bench_admin",
                password_hash=hash_password("SuperSecretAdminPass123!"),
                role="owner",
                is_active=True,
                created_at=datetime.now(timezone.utc),
            )
            session.add(adm)
            await session.commit()
        await engine.dispose()
    asyncio.run(seed())

    admin_token = create_access_token(
        admin_id=admin_id,
        username="bench_admin",
        role="owner",
        secret_key=cfg.master_key,
    )

    server_config = uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="warning", loop="asyncio")
    server = uvicorn.Server(server_config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}"
    timeout = time.time() + 6.0
    connected = False
    while time.time() < timeout:
        try:
            r = httpx.get(f"{url}/healthz", timeout=0.5)
            if r.status_code == 200:
                connected = True
                break
        except Exception:
            time.sleep(0.05)

    assert connected, "Live test server failed to bind within 6 seconds."

    yield {
        "url": url,
        "admin_token": admin_token,
        "admin_headers": {"Authorization": f"Bearer {admin_token}"},
    }

    server.should_exit = True
    thread.join(timeout=3.0)


def test_real_client_e2e_lifecycle(live_server, sample_payload_bytes):
    """
    Executes full client pairing, credentials file storage (POSIX 0600),
    authenticated biometric enrollment, verification, and revocation lifecycle
    over a real TCP socket.
    """
    server_url = live_server["url"]
    admin_headers = live_server["admin_headers"]

    with httpx.Client(base_url=server_url) as client:
        # 1. Admin issues pairing token
        r = client.post(
            "/v1/admin/devices/pairing-tokens",
            json={"name_hint": "kiosk_north", "scopes": ["verify", "enroll"]},
            headers=admin_headers,
        )
        assert r.status_code == 201
        tok_data = r.json()
        pairing_token = tok_data["token"]

        # 2. Client pairs with server using custom credentials file path
        with tempfile.TemporaryDirectory() as tmp_dir:
            creds_path = Path(tmp_dir) / "device_creds.json"

            # Pair using real freqid_client pair_device function over TCP
            creds = pair_device(
                server_url=server_url,
                token=pairing_token,
                name="kiosk_north",
                credentials_path=creds_path,
                software_version="0.1.0",
            )

            assert creds_path.is_file()
            st = os.stat(creds_path)
            mode = stat.S_IMODE(st.st_mode)
            assert mode & 0o077 == 0, f"Credentials file permissions must be 0600, got {oct(mode)}"

            device_id = creds["device_id"]
            auth = DeviceSignatureAuthenticator(credentials_path=creds_path)

            # 3. Client enrolls user "alice_smith"
            with FreqIDTransport(
                server_url=server_url,
                device_id=device_id,
                auth=auth,
            ) as transport:
                enroll_res = transport.enroll(
                    user_id="alice_smith",
                    payload_bytes_list=[sample_payload_bytes, sample_payload_bytes],
                )
                assert enroll_res.get("status") == "enrolled"
                assert enroll_res.get("user_id") == "alice_smith"

                # 4. Client verifies user "alice_smith"
                verify_res = transport.verify(
                    claimed_identity="alice_smith",
                    payload_bytes=sample_payload_bytes,
                )
                assert verify_res.get("status") == "success"
                assert verify_res.get("is_match") is True

                # 5. Revocation Lifecycle: Suspend device
                r_suspend = client.post(f"/v1/admin/devices/{device_id}/suspend", headers=admin_headers)
                assert r_suspend.status_code == 200

                # Verification must now immediately fail with 403 DeviceSuspended
                with pytest.raises(Exception) as exc_info:
                    transport.verify(claimed_identity="alice_smith", payload_bytes=sample_payload_bytes)
                assert "403" in str(exc_info.value) or "DEVICE_SUSPENDED" in str(exc_info.value)

                # 6. Resume device
                r_resume = client.post(f"/v1/admin/devices/{device_id}/resume", headers=admin_headers)
                assert r_resume.status_code == 200

                # Verification succeeds again
                verify_res2 = transport.verify(claimed_identity="alice_smith", payload_bytes=sample_payload_bytes)
                assert verify_res2.get("is_match") is True

                # 7. Permanent revocation
                r_revoke = client.post(f"/v1/admin/devices/{device_id}/revoke", headers=admin_headers)
                assert r_revoke.status_code == 200

                # Verification immediately fails with 403 DeviceRevoked
                with pytest.raises(Exception) as exc_info:
                    transport.verify(claimed_identity="alice_smith", payload_bytes=sample_payload_bytes)
                assert "403" in str(exc_info.value) or "DEVICE_REVOKED" in str(exc_info.value)


def test_authentication_latency_and_concurrency_benchmarks(live_server, sample_payload_bytes):
    """
    Measures:
    1. Client-side Ed25519 signature computation latency.
    2. Server-side Ed25519 signature verification + DB state lookup latency overhead.
    3. End-to-end request latency percentiles (p50, p95).
    4. Concurrency load test across worker levels (c=1, c=8, c=32).
    """
    server_url = live_server["url"]
    admin_headers = live_server["admin_headers"]

    with httpx.Client(base_url=server_url) as client:
        # 1. Setup paired device
        r = client.post(
            "/v1/admin/devices/pairing-tokens",
            json={"name_hint": "bench_kiosk", "scopes": ["verify", "enroll"]},
            headers=admin_headers,
        )
        token = r.json()["token"]

        with tempfile.TemporaryDirectory() as tmp_dir:
            creds_path = Path(tmp_dir) / "device_creds.json"
            creds = pair_device(
                server_url=server_url,
                token=token,
                name="bench_kiosk",
                credentials_path=creds_path,
                software_version="0.1.0",
            )
            device_id = creds["device_id"]
            auth = DeviceSignatureAuthenticator(credentials_path=creds_path)

            with FreqIDTransport(
                server_url=server_url,
                device_id=device_id,
                auth=auth,
            ) as transport:
                # Enroll benchmark identity
                transport.enroll(user_id="bench_user", payload_bytes_list=[sample_payload_bytes])

                # Benchmark 1: Client signature generation latency
                sig_latencies = []
                for _ in range(50):
                    t0 = time.perf_counter()
                    _ = auth.get_auth_headers(method="POST", path="/v1/verify", body=sample_payload_bytes)
                    sig_latencies.append((time.perf_counter() - t0) * 1000.0)

                p50_sig = np.percentile(sig_latencies, 50)
                p95_sig = np.percentile(sig_latencies, 95)
                print(f"\n[BENCHMARK] Client Ed25519 Sign Latency: p50={p50_sig:.3f}ms, p95={p95_sig:.3f}ms")
                assert p95_sig < 5.0, f"Ed25519 sign latency excessive: {p95_sig:.2f}ms"

                # Benchmark 2: End-to-end Verification latency under sequential load (c=1)
                seq_latencies = []
                for _ in range(25):
                    t0 = time.perf_counter()
                    res = transport.verify(claimed_identity="bench_user", payload_bytes=sample_payload_bytes)
                    seq_latencies.append((time.perf_counter() - t0) * 1000.0)
                    assert res.get("is_match") is True

                p50_seq = np.percentile(seq_latencies, 50)
                p95_seq = np.percentile(seq_latencies, 95)
                print(f"[BENCHMARK] Sequential Verify (c=1): p50={p50_seq:.2f}ms, p95={p95_seq:.2f}ms")

                # Benchmark 3: Concurrency load testing at c=8 and c=32
                for concurrency in (8, 32):
                    def send_one():
                        t_start = time.perf_counter()
                        headers = auth.get_auth_headers(method="POST", path="/v1/verify", body=sample_payload_bytes)
                        headers["Content-Type"] = "application/vnd.freqid.payload"
                        headers["X-Claimed-Identity"] = "bench_user"
                        with httpx.Client(base_url=server_url, timeout=10.0) as bench_c:
                            resp = bench_c.post("/v1/verify", content=sample_payload_bytes, headers=headers)
                        latency = (time.perf_counter() - t_start) * 1000.0
                        return resp.status_code, latency

                    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
                        futures = [executor.submit(send_one) for _ in range(concurrency)]
                        results = [f.result() for f in futures]

                    statuses = [s for s, _ in results]
                    latencies = [l for _, l in results]

                    p50 = np.percentile(latencies, 50)
                    p95 = np.percentile(latencies, 95)
                    rps = concurrency / (max(latencies) / 1000.0)

                    print(
                        f"[BENCHMARK] Concurrent Load (c={concurrency}): "
                        f"Success Rate={statuses.count(200)}/{concurrency}, "
                        f"p50={p50:.2f}ms, p95={p95:.2f}ms, Throughput={rps:.1f} req/s"
                    )
                    assert statuses.count(200) == concurrency, f"Failures under load c={concurrency}: {statuses}"
