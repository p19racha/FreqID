# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_store_contract.py: Parameterized contract test suite for TemplateStore implementations.
Verifies identical behavior, invariants, and error contracts across:
  - MemoryTemplateStore
  - PostgreSQLTemplateStore
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from freqid_server.crypto.envelope import TemplateEncryptor
from freqid_server.crypto.provider import EnvOrFileKeyProvider
from freqid_server.errors import OptimisticLockError
from freqid_server.storage.base import EnrolledTemplate, TemplateStore
from freqid_server.storage.memory import MemoryTemplateStore
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


def make_synthetic_template(
    user_id: str,
    model_version: str = "v1.0-ir18",
    seed: int = 42,
) -> EnrolledTemplate:
    rng = np.random.RandomState(seed)
    emb = rng.randn(512).astype(np.float32)
    emb = emb / np.linalg.norm(emb)
    return EnrolledTemplate(
        user_id=user_id,
        template_id=f"tmpl_{user_id}_{uuid.uuid4().hex[:8]}",
        model_version=model_version,
        embedding=emb,
        enrolled_at_iso=datetime.now(timezone.utc).isoformat(),
        frames_used=5,
        metadata={"device": "test-cam", "quality": 0.98},
    )


@pytest_asyncio.fixture(params=["memory", "postgres"])
async def template_store(request) -> TemplateStore:
    backend_type = request.param
    if backend_type == "memory":
        store = MemoryTemplateStore()
        yield store
    elif backend_type == "postgres":
        admin_engine = create_async_engine(ADMIN_DB_URL, echo=False)
        app_engine = create_async_engine(DEV_DB_URL, echo=False)
        session_factory = async_sessionmaker(app_engine, expire_on_commit=False)
        key_provider = EnvOrFileKeyProvider(default_key=TEST_MASTER_KEY)
        encryptor = TemplateEncryptor(key_provider)
        store = PostgreSQLTemplateStore(session_factory=session_factory, encryptor=encryptor, batch_size=2)

        # Truncate tables before test for clean isolation using admin role
        async with admin_engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE audit_events, templates, enrollment_sessions, users CASCADE;"))

        yield store

        # Cleanup after test
        async with admin_engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE audit_events, templates, enrollment_sessions, users CASCADE;"))
        await app_engine.dispose()
        await admin_engine.dispose()


@pytest.mark.asyncio
async def test_put_and_get_template(template_store: TemplateStore):
    template = make_synthetic_template("alice_01", seed=101)
    await template_store.put_template(template)

    retrieved = await template_store.get_template("alice_01")
    assert retrieved is not None
    assert retrieved.user_id == "alice_01"
    assert retrieved.template_id == template.template_id
    assert retrieved.model_version == "v1.0-ir18"
    assert retrieved.frames_used == 5
    assert retrieved.metadata.get("device") == "test-cam"
    assert np.allclose(retrieved.embedding, template.embedding, atol=1e-6)


@pytest.mark.asyncio
async def test_get_nonexistent_template(template_store: TemplateStore):
    res = await template_store.get_template("nonexistent_user")
    assert res is None


@pytest.mark.asyncio
async def test_delete_template(template_store: TemplateStore):
    template = make_synthetic_template("bob_02", seed=102)
    await template_store.put_template(template)

    # First delete succeeds
    deleted = await template_store.delete_template("bob_02")
    assert deleted is True

    # Subsequent get returns None
    assert await template_store.get_template("bob_02") is None

    # Second delete returns False
    deleted_again = await template_store.delete_template("bob_02")
    assert deleted_again is False


@pytest.mark.asyncio
async def test_list_templates_and_model_filtering(template_store: TemplateStore):
    t1 = make_synthetic_template("u1", model_version="v1.0-ir18", seed=1)
    t2 = make_synthetic_template("u2", model_version="v1.0-ir18", seed=2)
    t3 = make_synthetic_template("u3", model_version="v2.0-ir50", seed=3)
    t4 = make_synthetic_template("u4", model_version="v1.0-ir18", seed=4)

    await template_store.put_template(t1)
    await template_store.put_template(t2)
    await template_store.put_template(t3)
    await template_store.put_template(t4)

    # List all
    all_templates = await template_store.list_templates()
    assert len(all_templates) == 4
    user_ids = {t.user_id for t in all_templates}
    assert user_ids == {"u1", "u2", "u3", "u4"}

    # Filter by model version v1.0-ir18
    v1_templates = await template_store.list_templates(model_version="v1.0-ir18")
    assert len(v1_templates) == 3
    assert {t.user_id for t in v1_templates} == {"u1", "u2", "u4"}

    # Filter by model version v2.0-ir50
    v2_templates = await template_store.list_templates(model_version="v2.0-ir50")
    assert len(v2_templates) == 1
    assert v2_templates[0].user_id == "u3"


@pytest.mark.asyncio
async def test_optimistic_concurrency_control(template_store: TemplateStore):
    template = make_synthetic_template("carol_03", seed=103)
    # 1. Initial insert
    await template_store.put_template(template)
    t1 = await template_store.get_template("carol_03")
    assert t1 is not None

    # 2. Update with correct expected_version=1
    updated_template = make_synthetic_template("carol_03", seed=104)
    await template_store.put_template(updated_template, expected_version=1)
    t2 = await template_store.get_template("carol_03")
    assert t2 is not None
    assert np.allclose(t2.embedding, updated_template.embedding, atol=1e-6)

    # 3. Update with stale expected_version=1 must fail
    stale_template = make_synthetic_template("carol_03", seed=105)
    with pytest.raises(OptimisticLockError) as exc_info:
        await template_store.put_template(stale_template, expected_version=1)
    assert "Optimistic" in str(exc_info.value)

    # 4. Update with expected_version=2 succeeds
    await template_store.put_template(stale_template, expected_version=2)
    t3 = await template_store.get_template("carol_03")
    assert t3 is not None
    assert np.allclose(t3.embedding, stale_template.embedding, atol=1e-6)


@pytest.mark.asyncio
async def test_delete_user_completely_gdpr(template_store: TemplateStore):
    template = make_synthetic_template("david_04", seed=106)
    await template_store.put_template(template)

    # Verify template exists
    assert await template_store.get_template("david_04") is not None

    # Complete right-to-be-forgotten deletion
    deleted = await template_store.delete_user_completely("david_04")
    assert deleted is True

    # Template is removed
    assert await template_store.get_template("david_04") is None

    # Subsequent deletion returns False
    assert await template_store.delete_user_completely("david_04") is False


@pytest.mark.asyncio
async def test_store_ping(template_store: TemplateStore):
    assert await template_store.ping() is True
