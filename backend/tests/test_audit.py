# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_audit.py: Integration and unit tests for the asynchronous PostgreSQL audit subsystem.
Tests:
  - Non-blocking emission and batch insertion via PostgresAuditSink
  - Anti-hill-climbing score bucketing and client IP pseudonymization
  - Load shedding under queue saturation without blocking API callers
  - Database role append-only enforcement (UPDATE/DELETE denied for app role)
  - Tamper-evident hash chaining and verification
  - Automated retention pruning with freqid_maint role
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

# Ensure backend root is on sys.path to import scripts
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
from sqlalchemy import select, text, update
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from freqid_server.audit.base import AuditEvent, coarse_score_bucket, hash_client_ip
from freqid_server.audit.postgres import PostgresAuditSink
from freqid_server.storage.models import AuditEventOrm

APP_DB_URL = os.environ.get(
    "FREQID_TEST_APP_DB_URL",
    "postgresql+asyncpg://freqid_app:freqid_app_dev_secret@127.0.0.1:54322/freqid",
)
ADMIN_DB_URL = os.environ.get(
    "FREQID_TEST_ADMIN_DB_URL",
    "postgresql+asyncpg://freqid_admin:freqid_admin_dev_password@127.0.0.1:54322/freqid",
)
MAINT_DB_URL = os.environ.get(
    "FREQID_TEST_MAINT_DB_URL",
    "postgresql+asyncpg://freqid_maint:freqid_maint_dev_secret@127.0.0.1:54322/freqid",
)


@pytest_asyncio.fixture
async def clean_audit_db():
    admin_engine = create_async_engine(ADMIN_DB_URL, echo=False)
    async with admin_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE audit_events, templates, enrollment_sessions, users CASCADE;"))
    yield
    async with admin_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE audit_events, templates, enrollment_sessions, users CASCADE;"))
    await admin_engine.dispose()


def test_coarse_score_bucketing():
    assert coarse_score_bucket(None) is None
    assert coarse_score_bucket(0.10) == "very_low"
    assert coarse_score_bucket(0.25) == "low"
    assert coarse_score_bucket(0.40) == "medium"
    assert coarse_score_bucket(0.60) == "high"
    assert coarse_score_bucket(0.85) == "very_high"


def test_hash_client_ip():
    assert hash_client_ip(None) is None
    assert hash_client_ip("127.0.0.1") is None
    assert hash_client_ip("localhost") is None
    assert hash_client_ip("unknown") is None

    h1 = hash_client_ip("203.0.113.195", salt="salt1")
    h2 = hash_client_ip("203.0.113.195", salt="salt1")
    h3 = hash_client_ip("203.0.113.195", salt="salt2")

    assert h1 is not None and len(h1) == 16
    assert h1 == h2
    assert h1 != h3


@pytest.mark.asyncio
async def test_audit_sink_batch_drain_and_flush(clean_audit_db):
    app_engine = create_async_engine(APP_DB_URL, echo=False)
    session_factory = async_sessionmaker(app_engine, expire_on_commit=False)

    sink = PostgresAuditSink(
        session_factory=session_factory,
        batch_size=10,
        flush_interval_seconds=0.05,
        enable_hash_chain=False,
    )

    await sink.start()

    # Emit 5 events
    for i in range(5):
        event = AuditEvent(
            event_type="verify",
            principal_type="device",
            decision="match" if i % 2 == 0 else "no_match",
            request_id=f"req_{i}",
            score_bucket=coarse_score_bucket(0.45),
            client_ip="198.51.100.2",
        )
        await sink.emit(event)

    # Allow worker to drain
    await asyncio.sleep(0.15)
    await sink.shutdown()

    # Verify rows in PostgreSQL
    async with session_factory() as session:
        stmt = select(AuditEventOrm).order_by(AuditEventOrm.request_id.asc())
        res = await session.execute(stmt)
        rows = list(res.scalars())

        assert len(rows) == 5
        assert rows[0].request_id == "req_0"
        assert rows[0].decision == "match"
        assert rows[0].score_bucket == "medium"
        assert rows[1].decision == "no_match"
        assert rows[0].client_ip_hash is not None

    await app_engine.dispose()


@pytest.mark.asyncio
async def test_audit_sink_load_shedding():
    app_engine = create_async_engine(APP_DB_URL, echo=False)
    session_factory = async_sessionmaker(app_engine, expire_on_commit=False)

    # Sink with queue size 3, worker not started
    sink = PostgresAuditSink(
        session_factory=session_factory,
        max_queue_size=3,
        batch_size=2,
    )

    for i in range(10):
        await sink.emit(
            AuditEvent(
                event_type="identify",
                principal_type="device",
                decision="match",
                request_id=f"flood_{i}",
            )
        )

    assert sink.dropped_count == 7
    await app_engine.dispose()


@pytest.mark.asyncio
async def test_append_only_role_permissions(clean_audit_db):
    """Verifies database-level enforcement: freqid_app cannot UPDATE or DELETE audit events."""
    admin_engine = create_async_engine(ADMIN_DB_URL, echo=False)
    app_engine = create_async_engine(APP_DB_URL, echo=False)

    admin_session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    app_session_factory = async_sessionmaker(app_engine, expire_on_commit=False)

    ev_id = uuid.uuid4()
    # 1. Admin creates an audit record
    async with admin_session_factory() as session, session.begin():
        event = AuditEventOrm(
            id=ev_id,
            event_type="enroll",
            principal_type="admin",
            decision="match",
            request_id="perm_req_1",
        )
        session.add(event)

    # 2. App role CAN read
    async with app_session_factory() as session:
        res = await session.execute(select(AuditEventOrm).where(AuditEventOrm.id == ev_id))
        row = res.scalar_one_or_none()
        assert row is not None

    # 3. App role CANNOT update
    with pytest.raises(ProgrammingError):
        async with app_session_factory() as session, session.begin():
            await session.execute(
                update(AuditEventOrm)
                .where(AuditEventOrm.id == ev_id)
                .values(decision="tampered")
            )

    # 4. App role CANNOT delete
    with pytest.raises(ProgrammingError):
        async with app_session_factory() as session, session.begin():
            await session.execute(
                text("DELETE FROM audit_events WHERE id = :id"), {"id": ev_id}
            )

    await app_engine.dispose()
    await admin_engine.dispose()


@pytest.mark.asyncio
async def test_tamper_evident_hash_chain(clean_audit_db):
    """Tests hash chaining: valid verification on clean log, alert on tampered log."""
    from scripts.verify_audit_chain import verify_chain

    app_engine = create_async_engine(APP_DB_URL, echo=False)
    admin_engine = create_async_engine(ADMIN_DB_URL, echo=False)

    session_factory = async_sessionmaker(app_engine, expire_on_commit=False)
    admin_session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)

    sink = PostgresAuditSink(
        session_factory=session_factory,
        batch_size=5,
        flush_interval_seconds=0.05,
        enable_hash_chain=True,
    )
    await sink.start()

    for i in range(5):
        await sink.emit(
            AuditEvent(
                event_type="verify",
                principal_type="device",
                decision="match" if i % 2 == 0 else "no_match",
                request_id=f"chain_req_{i}",
            )
        )

    await asyncio.sleep(0.15)
    await sink.shutdown()

    # Verify clean chain passes
    is_valid = await verify_chain(APP_DB_URL)
    assert is_valid is True

    # Tamper with record #3 using admin connection
    async with admin_session_factory() as session, session.begin():
        stmt = (
            update(AuditEventOrm)
            .where(AuditEventOrm.request_id == "chain_req_2")
            .values(decision="tampered_decision")
        )
        await session.execute(stmt)

    # Verify detection of broken chain
    is_valid_tampered = await verify_chain(APP_DB_URL)
    assert is_valid_tampered is False

    await app_engine.dispose()
    await admin_engine.dispose()


@pytest.mark.asyncio
async def test_audit_retention_purge(clean_audit_db):
    """Tests retention purging: freqid_maint can delete events older than cutoff."""
    from scripts.audit_retention import run_retention

    admin_engine = create_async_engine(ADMIN_DB_URL, echo=False)
    admin_session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)

    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=100)

    # Insert 3 old events and 2 fresh events
    async with admin_session_factory() as session, session.begin():
        for i in range(3):
            session.add(
                AuditEventOrm(
                    id=uuid.uuid4(),
                    event_time=old_time,
                    event_type="verify",
                    principal_type="device",
                    decision="match",
                    request_id=f"old_{i}",
                )
            )
        for i in range(2):
            session.add(
                AuditEventOrm(
                    id=uuid.uuid4(),
                    event_time=now,
                    event_type="verify",
                    principal_type="device",
                    decision="match",
                    request_id=f"fresh_{i}",
                )
            )

    # Run retention purge with 90-day retention
    purged_count = await run_retention(
        db_url=MAINT_DB_URL,
        retention_days=90,
        dry_run=False,
    )
    assert purged_count == 3

    # Check remaining records
    async with admin_session_factory() as session:
        res = await session.execute(select(AuditEventOrm))
        remaining = list(res.scalars())
        assert len(remaining) == 2
        assert all("fresh" in r.request_id for r in remaining)

    await admin_engine.dispose()
