# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
conftest.py: Shared fixtures and synthetic data generators for freqid-server tests.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import freqid_core as fq
import httpx
import numpy as np
import pytest
import pytest_asyncio

from freqid_server.config import ServerConfig
from freqid_server.main import create_app
from freqid_server.storage.memory import MemoryTemplateStore


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Ensures test model checkpoints and database tables/roles are provisioned."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    backend_scripts = repo_root / "backend" / "scripts"
    if str(backend_scripts) not in sys.path:
        sys.path.insert(0, str(backend_scripts))

    try:
        from init_test_env import ensure_test_checkpoints, init_postgres_db

        ensure_test_checkpoints()

        admin_db_url = os.environ.get(
            "FREQID_TEST_ADMIN_DB_URL",
            os.environ.get(
                "FREQID_DATABASE_URL",
                "postgresql+asyncpg://freqid_admin:freqid_admin_dev_password@127.0.0.1:54322/freqid",
            ),
        )
        asyncio.run(init_postgres_db(admin_db_url))
    except Exception:
        pass


@pytest.fixture(scope="session")
def sample_payload_data() -> np.ndarray:
    """Deterministic synthetic 27-channel partial frequency array."""
    rng = np.random.RandomState(42)
    return rng.randn(27, 112, 112).astype(np.float32)


@pytest.fixture(scope="session")
def sample_payload(sample_payload_data: np.ndarray) -> fq.PartialFacePayload:
    return fq.PartialFacePayload(data=sample_payload_data)


@pytest.fixture(scope="session")
def sample_payload_bytes(sample_payload: fq.PartialFacePayload) -> bytes:
    return sample_payload.to_bytes()


@pytest.fixture
def test_config() -> ServerConfig:
    return ServerConfig(
        host="127.0.0.1",
        port=8000,
        environment="test",
        model_path="research/outputs/checkpoints/partialface_ir_18.onnx",
        model_backend="onnx",
        model_version="v1.0-ir18",
        device="cpu",
        decision_threshold=0.35,
        mask_scores_in_production=False,  # Unmask scores for assertions in test suite
        rate_limit_per_minute=200,
        max_failed_verifications_lockout=3,
        lockout_duration_seconds=5,
        static_tokens={
            "dev_verify_token": ["verify"],
            "dev_kiosk_token": ["verify", "identify"],
            "dev_enroll_token": ["enroll"],
            "dev_admin_token": ["verify", "identify", "enroll", "admin"],
        },
    )


@pytest_asyncio.fixture
async def app_instance(test_config: ServerConfig):
    store = MemoryTemplateStore()
    app = create_app(config=test_config, store=store)
    app.state.inference.start()
    yield app
    app.state.inference.shutdown()


@pytest_asyncio.fixture
async def client(app_instance) -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app_instance)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {
        "verify": {
            "Content-Type": "application/vnd.freqid.payload",
            "X-Device-ID": "test-device-1",
            "X-Nonce": secrets.token_hex(16),
            "Authorization": "Bearer dev_verify_token",
        },
        "identify": {
            "Content-Type": "application/vnd.freqid.payload",
            "X-Device-ID": "test-kiosk-1",
            "X-Nonce": secrets.token_hex(16),
            "Authorization": "Bearer dev_kiosk_token",
        },
        "enroll": {
            "Content-Type": "application/vnd.freqid.payload",
            "X-Device-ID": "test-admin-terminal",
            "Authorization": "Bearer dev_enroll_token",
        },
        "admin": {
            "Authorization": "Bearer dev_admin_token",
        },
    }
