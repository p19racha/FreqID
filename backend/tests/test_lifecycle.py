# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_lifecycle.py: Identity and biometric template lifecycle integration tests.
Tests:
  - Duplicate face detection policies (warn vs block)
  - Re-enrollment flag enforcement (X-Re-Enroll)
  - User disable and enable state machine transitions and gallery eviction
  - Complete GDPR Right-to-be-Forgotten deletion and audit anonymization
  - Model version migration report
"""

from __future__ import annotations

import os

import freqid_core as fq
import httpx
import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from freqid_server.config import ServerConfig
from freqid_server.crypto.envelope import TemplateEncryptor
from freqid_server.crypto.provider import EnvOrFileKeyProvider
from freqid_server.main import create_app
from freqid_server.services.enrollment import EnrollmentService
from freqid_server.storage.models import AuditEventOrm, TemplateOrm, UserOrm
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


@pytest_asyncio.fixture
async def clean_postgres_db():
    admin_engine = create_async_engine(ADMIN_DB_URL, echo=False)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE audit_events, templates, enrollment_sessions, users CASCADE;")
        )
    yield
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE audit_events, templates, enrollment_sessions, users CASCADE;")
        )
    await admin_engine.dispose()


@pytest_asyncio.fixture
async def app_with_postgres(clean_postgres_db):
    engine = create_async_engine(DEV_DB_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    key_provider = EnvOrFileKeyProvider(default_key=TEST_MASTER_KEY)
    encryptor = TemplateEncryptor(key_provider)
    store = PostgreSQLTemplateStore(session_factory=session_factory, encryptor=encryptor)

    cfg = ServerConfig(
        host="127.0.0.1",
        port=8000,
        environment="test",
        storage_backend="postgres",
        database_url=DEV_DB_URL,
        model_path="research/outputs/checkpoints/partialface_ir_18.onnx",
        model_backend="onnx",
        model_version="v1.0-ir18",
        decision_threshold=0.35,
        enroll_duplicate_check_policy="warn",
        enroll_duplicate_threshold=0.60,
        mask_scores_in_production=False,
        static_tokens={
            "dev_verify_token": ["verify"],
            "dev_identify_token": ["identify"],
            "dev_enroll_token": ["enroll"],
            "dev_admin_token": ["verify", "identify", "enroll", "admin"],
        },
    )

    app = create_app(config=cfg, store=store)
    app.state.inference.start()
    yield app
    app.state.inference.shutdown()
    await engine.dispose()


@pytest_asyncio.fixture
async def api_client(app_with_postgres) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app_with_postgres)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def make_payload_stream(num_frames: int = 3, seed: int = 42) -> bytes:
    rng = np.random.RandomState(seed)
    payloads = []
    for _ in range(num_frames):
        data = rng.randn(27, 112, 112).astype(np.float32)
        payloads.append(fq.PartialFacePayload(data=data))
    return EnrollmentService.pack_framed_payloads(payloads)


@pytest.mark.asyncio
async def test_re_enrollment_flag_enforcement(api_client: httpx.AsyncClient):
    body = make_payload_stream(num_frames=3, seed=1)

    # 1. Initial enrollment succeeds
    resp1 = await api_client.post(
        "/v1/enroll",
        content=body,
        headers={
            "Content-Type": "application/vnd.freqid.payload",
            "X-Device-ID": "test-device",
            "X-User-ID": "user_re_enroll_test",
            "Authorization": "Bearer dev_admin_token",
        },
    )
    assert resp1.status_code == 201
    assert resp1.json()["status"] == "enrolled"

    # 2. Re-enrolling without X-Re-Enroll: true fails with 409 Conflict
    resp2 = await api_client.post(
        "/v1/enroll",
        content=body,
        headers={
            "Content-Type": "application/vnd.freqid.payload",
            "X-Device-ID": "test-device",
            "X-User-ID": "user_re_enroll_test",
            "Authorization": "Bearer dev_admin_token",
        },
    )
    assert resp2.status_code == 409
    assert "already enrolled" in resp2.json()["error"]["message"]

    # 3. Re-enrolling WITH X-Re-Enroll: true succeeds
    resp3 = await api_client.post(
        "/v1/enroll",
        content=body,
        headers={
            "Content-Type": "application/vnd.freqid.payload",
            "X-Device-ID": "test-device",
            "X-User-ID": "user_re_enroll_test",
            "X-Re-Enroll": "true",
            "Authorization": "Bearer dev_admin_token",
        },
    )
    assert resp3.status_code == 201
    assert resp3.json()["status"] == "enrolled"


@pytest.mark.asyncio
async def test_duplicate_face_detection_warn_and_block(
    app_with_postgres, api_client: httpx.AsyncClient
):
    body = make_payload_stream(num_frames=3, seed=99)

    # 1. Enroll user_alpha
    resp1 = await api_client.post(
        "/v1/enroll",
        content=body,
        headers={
            "Content-Type": "application/vnd.freqid.payload",
            "X-Device-ID": "cam-1",
            "X-User-ID": "user_alpha",
            "Authorization": "Bearer dev_admin_token",
        },
    )
    assert resp1.status_code == 201
    assert resp1.json().get("duplicate_warning") is None

    # 2. Enroll user_beta using the EXACT SAME faces under policy="warn"
    resp2 = await api_client.post(
        "/v1/enroll",
        content=body,
        headers={
            "Content-Type": "application/vnd.freqid.payload",
            "X-Device-ID": "cam-1",
            "X-User-ID": "user_beta",
            "Authorization": "Bearer dev_admin_token",
        },
    )
    assert resp2.status_code == 201
    assert "duplicate_warning" in resp2.json()
    assert "user_alpha" in resp2.json()["duplicate_warning"]

    # 3. Change policy to "block"
    app_with_postgres.state.config.enroll_duplicate_check_policy = "block"
    resp3 = await api_client.post(
        "/v1/enroll",
        content=body,
        headers={
            "Content-Type": "application/vnd.freqid.payload",
            "X-Device-ID": "cam-1",
            "X-User-ID": "user_gamma",
            "Authorization": "Bearer dev_admin_token",
        },
    )
    assert resp3.status_code == 409
    assert "Duplicate biometric face detected" in resp3.json()["error"]["message"]


@pytest.mark.asyncio
async def test_user_disable_enable_lifecycle(app_with_postgres, api_client: httpx.AsyncClient):
    body = make_payload_stream(num_frames=3, seed=55)

    # 1. Enroll user
    await api_client.post(
        "/v1/enroll",
        content=body,
        headers={
            "Content-Type": "application/vnd.freqid.payload",
            "X-Device-ID": "cam-1",
            "X-User-ID": "user_toggle",
            "Authorization": "Bearer dev_admin_token",
        },
    )

    # Verify user exists in gallery
    assert "user_toggle" in app_with_postgres.state.gallery.identities

    # 2. Disable user
    dis_resp = await api_client.post(
        "/v1/users/user_toggle/disable",
        headers={"Authorization": "Bearer dev_admin_token"},
    )
    assert dis_resp.status_code == 200
    assert dis_resp.json()["status"] == "disabled"

    # Must be evicted from gallery
    assert "user_toggle" not in app_with_postgres.state.gallery.identities

    # 3. Enable user
    en_resp = await api_client.post(
        "/v1/users/user_toggle/enable",
        headers={"Authorization": "Bearer dev_admin_token"},
    )
    assert en_resp.status_code == 200
    assert en_resp.json()["status"] == "active"

    # Must be restored to gallery
    assert "user_toggle" in app_with_postgres.state.gallery.identities


@pytest.mark.asyncio
async def test_gdpr_right_to_be_forgotten_complete_deletion(
    clean_postgres_db, api_client: httpx.AsyncClient
):
    body = make_payload_stream(num_frames=3, seed=77)

    # 1. Enroll user
    await api_client.post(
        "/v1/enroll",
        content=body,
        headers={
            "Content-Type": "application/vnd.freqid.payload",
            "X-Device-ID": "cam-1",
            "X-User-ID": "user_gdpr_target",
            "Authorization": "Bearer dev_admin_token",
        },
    )

    # 2. Export user profile
    exp_resp = await api_client.get(
        "/v1/users/user_gdpr_target/export",
        headers={"Authorization": "Bearer dev_admin_token"},
    )
    assert exp_resp.status_code == 200
    assert exp_resp.json()["user_id"] == "user_gdpr_target"
    assert "template_id" in exp_resp.json()["template_metadata"]

    # 3. Delete user completely
    del_resp = await api_client.delete(
        "/v1/users/user_gdpr_target",
        headers={"Authorization": "Bearer dev_admin_token"},
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"

    # 4. Check DB directly: verify zero records in users and templates
    admin_engine = create_async_engine(ADMIN_DB_URL, echo=False)
    session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with session_factory() as session:
        u_res = await session.execute(
            select(UserOrm).where(UserOrm.external_id == "user_gdpr_target")
        )
        assert u_res.scalar_one_or_none() is None

        t_res = await session.execute(select(TemplateOrm))
        assert len(list(t_res.scalars())) == 0

        # Verify any audit events have user_id anonymized to NULL
        a_res = await session.execute(select(AuditEventOrm))
        for ev in a_res.scalars():
            assert ev.user_id is None

    await admin_engine.dispose()


@pytest.mark.asyncio
async def test_model_migration_report(api_client: httpx.AsyncClient):
    # Call migration report endpoint
    resp = await api_client.get("/v1/model/migration-report")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_model_version"] == "v1.0-ir18"
    assert "total_templates" in data
    assert "compatible_templates" in data
    assert "needs_reenrollment_count" in data
