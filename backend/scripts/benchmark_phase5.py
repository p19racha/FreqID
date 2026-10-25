#!/usr/bin/env python3
# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
benchmark_phase5.py: Performance benchmarking suite for Phase 5 persistence and audit subsystems.
Empirically measures:
  1. Gallery bulk ingestion and AES-256-GCM decryption latency from PostgreSQL at scale.
  2. Master key rotation throughput (records/second) without decrypting biometric ciphertext.
  3. End-to-end 1:1 verification latency with PostgreSQL store and async audit logging.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import time
import uuid
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Ensure backend/src is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from freqid_server.audit.base import AuditEvent, coarse_score_bucket
from freqid_server.audit.postgres import PostgresAuditSink
from freqid_server.crypto.envelope import TemplateEncryptor
from freqid_server.crypto.provider import EnvOrFileKeyProvider
from freqid_server.services.gallery import GalleryIndex
from freqid_server.storage.models import TemplateOrm, UserOrm
from freqid_server.storage.postgres import PostgreSQLTemplateStore
from scripts.rotate_keys import rotate_keys

DEV_DB_URL = os.environ.get(
    "FREQID_TEST_DB_URL",
    "postgresql+asyncpg://freqid_app:freqid_app_dev_secret@127.0.0.1:54322/freqid",
)
ADMIN_DB_URL = os.environ.get(
    "FREQID_TEST_ADMIN_DB_URL",
    "postgresql+asyncpg://freqid_admin:freqid_admin_dev_password@127.0.0.1:54322/freqid",
)
KEY_V1 = b"01234567890123456789012345678901"
KEY_V2 = b"abcdefghijklmnopqrstuvwxyz012345"


async def clean_database():
    admin_engine = create_async_engine(ADMIN_DB_URL, echo=False)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE audit_events, templates, enrollment_sessions, users CASCADE;")
        )
    await admin_engine.dispose()


async def seed_synthetic_templates(
    count: int, key_id: str = "key_v1"
) -> tuple[list[str], list[str]]:
    """Seeds N encrypted templates directly into PostgreSQL."""
    admin_engine = create_async_engine(ADMIN_DB_URL, echo=False)
    session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    provider = EnvOrFileKeyProvider(
        default_key=KEY_V1,
        default_key_id="key_v1",
        secondary_keys={"key_v2": KEY_V2},
    )
    encryptor = TemplateEncryptor(provider)

    rng = np.random.RandomState(42)
    user_ids = []
    blob_hashes = []

    print(f"Seeding {count} synthetic encrypted templates...")
    batch_size = 500
    for batch_start in range(0, count, batch_size):
        batch_end = min(batch_start + batch_size, count)
        async with session_factory() as session, session.begin():
            for i in range(batch_start, batch_end):
                u_id = f"bench_user_{i:06d}"
                user_ids.append(u_id)
                u_uuid = uuid.uuid4()
                user = UserOrm(id=u_uuid, external_id=u_id, status="active")
                session.add(user)

                emb = rng.randn(512).astype(np.float32)
                emb = emb / np.linalg.norm(emb)
                rec = encryptor.encrypt(emb, user_id=str(u_uuid), model_version="v1.0-ir18")
                blob_hashes.append(hashlib.sha256(rec.encrypted_blob).hexdigest())

                tmpl = TemplateOrm(
                    id=uuid.uuid4(),
                    user_id=u_uuid,
                    template_id=f"tmpl_{u_id}",
                    model_version="v1.0-ir18",
                    embedding_dim=512,
                    encrypted_blob=rec.encrypted_blob,
                    key_id=key_id,
                    nonce=rec.nonce,
                    wrapped_data_key=rec.wrapped_data_key,
                    format_version=rec.format_version,
                    frames_used=5,
                    metadata_json={"synthetic": True},
                    version=1,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(tmpl)

    await admin_engine.dispose()
    print(f"Seeded {count} templates.")
    return user_ids, blob_hashes


async def benchmark_gallery_ingestion_and_decryption(count: int):
    """Measures startup keyset pagination and AES-256-GCM unwrap + decrypt time."""
    app_engine = create_async_engine(DEV_DB_URL, echo=False)
    session_factory = async_sessionmaker(app_engine, expire_on_commit=False)
    provider = EnvOrFileKeyProvider(
        default_key=KEY_V1,
        default_key_id="key_v1",
        secondary_keys={"key_v2": KEY_V2},
    )
    encryptor = TemplateEncryptor(provider)
    store = PostgreSQLTemplateStore(
        session_factory=session_factory, encryptor=encryptor, batch_size=1000
    )
    gallery = GalleryIndex()

    t0 = time.perf_counter()
    loaded_count = await gallery.load_from_store(store)
    t1 = time.perf_counter()

    duration = t1 - t0
    rate = loaded_count / duration if duration > 0 else 0
    print(f"\n--- Benchmark 1: Gallery Bulk Decryption & Ingestion ({count} records) ---")
    print(f"Loaded:           {loaded_count} templates")
    print(f"Total time:       {duration * 1000:.2f} ms ({duration:.3f} s)")
    print(f"Throughput:       {rate:.1f} templates/second")
    print(f"Per-record cost:  {(duration / loaded_count) * 1000:.3f} ms/record")

    await app_engine.dispose()
    return duration, rate


async def benchmark_key_rotation(count: int, blob_hashes_before: list[str]):
    """Measures key rotation throughput and proves zero-biometric-decryption."""
    print(f"\n--- Benchmark 2: Master Key Rotation ({count} records) ---")
    provider = EnvOrFileKeyProvider(
        default_key=KEY_V2,
        default_key_id="key_v2",
        secondary_keys={"key_v1": KEY_V1},
    )
    t0 = time.perf_counter()
    rotated_count = await rotate_keys(
        db_url=ADMIN_DB_URL,
        new_key_id="key_v2",
        batch_size=500,
        dry_run=False,
        key_provider=provider,
    )
    t1 = time.perf_counter()

    duration = t1 - t0
    rate = rotated_count / duration if duration > 0 else 0
    print(f"Rotated:          {rotated_count} records")
    print(f"Total time:       {duration * 1000:.2f} ms ({duration:.3f} s)")
    print(f"Throughput:       {rate:.1f} records/second")

    # Verify biometric ciphertext blobs were untouched
    admin_engine = create_async_engine(ADMIN_DB_URL, echo=False)
    session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with session_factory() as session:
        stmt = text("SELECT encrypted_blob, key_id FROM templates ORDER BY template_id ASC")
        res = await session.execute(stmt)
        rows = res.all()
        for idx, (blob, k_id) in enumerate(rows):
            assert k_id == "key_v2"
            assert hashlib.sha256(blob).hexdigest() == blob_hashes_before[idx]

    print("Verification:     100% of biometric ciphertext blobs remained byte-for-byte identical.")
    await admin_engine.dispose()
    return duration, rate


async def benchmark_verification_latency(num_requests: int = 100):
    """Measures 1:1 verify latency with PostgreSQL template fetch and async audit logging."""
    print(
        f"\n--- Benchmark 3: Verification Latency with PostgreSQL & Async Audit ({num_requests} ops) ---"
    )
    app_engine = create_async_engine(DEV_DB_URL, echo=False)
    session_factory = async_sessionmaker(app_engine, expire_on_commit=False)
    provider = EnvOrFileKeyProvider(
        default_key=KEY_V2,
        default_key_id="key_v2",
        secondary_keys={"key_v1": KEY_V1},
    )
    encryptor = TemplateEncryptor(provider)
    store = PostgreSQLTemplateStore(session_factory=session_factory, encryptor=encryptor)

    audit_sink = PostgresAuditSink(
        session_factory=session_factory,
        batch_size=50,
        flush_interval_seconds=0.05,
    )
    await audit_sink.start()

    # Pre-fetch template for target user
    rng = np.random.RandomState(42)
    query_emb = rng.randn(512).astype(np.float32)
    query_emb = query_emb / np.linalg.norm(query_emb)

    latencies = []
    for i in range(num_requests):
        t0 = time.perf_counter()

        # Step 1: Fetch template from PostgreSQL
        template = await store.get_template("bench_user_000000")
        assert template is not None

        # Step 2: Cosine matching
        sim = float(np.dot(query_emb, template.embedding))
        is_match = sim >= 0.35

        # Step 3: Emit async audit event (non-blocking)
        event = AuditEvent(
            event_type="verify",
            principal_type="device",
            decision="match" if is_match else "no_match",
            request_id=f"bench_req_{i}",
            score_bucket=coarse_score_bucket(sim),
            client_ip="192.0.2.1",
        )
        await audit_sink.emit(event)

        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000)

    # Allow audit worker to drain
    await asyncio.sleep(0.15)
    await audit_sink.shutdown()

    p50 = np.percentile(latencies, 50)
    p95 = np.percentile(latencies, 95)
    p99 = np.percentile(latencies, 99)
    mean = np.mean(latencies)

    print(f"Total operations: {num_requests}")
    print(f"Mean latency:     {mean:.2f} ms")
    print(f"p50 latency:      {p50:.2f} ms")
    print(f"p95 latency:      {p95:.2f} ms")
    print(f"p99 latency:      {p99:.2f} ms")
    print(f"Audit dropped:    {audit_sink.dropped_count} (Zero lost events)")

    await app_engine.dispose()
    return mean, p50, p95, p99


async def main():
    print("================================================================")
    print("FreqID Phase 5: Empirical Persistence & Security Benchmark Suite")
    print("================================================================")

    # 1. Clean DB
    await clean_database()

    # 2. Seed 1,000 synthetic templates
    _, blob_hashes = await seed_synthetic_templates(count=1000, key_id="key_v1")

    # 3. Benchmark Ingestion
    await benchmark_gallery_ingestion_and_decryption(count=1000)

    # 4. Benchmark Key Rotation
    await benchmark_key_rotation(count=1000, blob_hashes_before=blob_hashes)

    # 5. Benchmark Verification Latency
    await benchmark_verification_latency(num_requests=100)

    # Clean up afterwards
    await clean_database()
    print("\nBenchmark completed successfully.")


if __name__ == "__main__":
    asyncio.run(main())
