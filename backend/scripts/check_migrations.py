#!/usr/bin/env python3
# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
check_migrations.py: CI verification script that tests upgrade/downgrade cycles
on a clean throwaway database, including upgrading from Phase 5 schema with existing data.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid

import asyncpg
from alembic.config import Config

from alembic import command


async def create_db(admin_url: str, db_name: str) -> None:
    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()


async def drop_db(admin_url: str, db_name: str) -> None:
    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute(
            f"""
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = '{db_name}'
              AND pid <> pg_backend_pid();
            """
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
    finally:
        await conn.close()


async def insert_phase5_test_data(db_url: str) -> None:
    """Inserts mock Phase 5 data including audit events with null and string device/admin IDs."""
    conn = await asyncpg.connect(db_url)
    try:
        user_id = uuid.uuid4()
        template_id = uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO users (id, external_id, status, created_at, updated_at)
            VALUES ($1, 'test_user_p5', 'active', NOW(), NOW())
            """,
            user_id,
        )
        await conn.execute(
            """
            INSERT INTO templates (
                id, user_id, template_id, model_version, embedding_dim,
                encrypted_blob, key_id, nonce, wrapped_data_key,
                format_version, frames_used, metadata_json, version,
                created_at, updated_at
            ) VALUES (
                $1, $2, 'tmpl_test_p5', 'v1.0-ir18', 512,
                $3, 'key_v1', $4, $5,
                1, 1, '{}'::jsonb, 1,
                NOW(), NOW()
            )
            """,
            template_id,
            user_id,
            b"fake_encrypted_blob_512",
            b"123456789012",
            b"fake_wrapped_key_32",
        )
        # Audit event 1: NULL device_id and admin_id
        await conn.execute(
            """
            INSERT INTO audit_events (
                id, event_time, event_type, principal_type, principal_id,
                device_id, admin_id, user_id, decision, request_id
            ) VALUES (
                $1, NOW(), 'verify', 'anonymous', NULL,
                NULL, NULL, $2, 'no_match', 'req-null-dev'
            )
            """,
            uuid.uuid4(),
            user_id,
        )
        # Audit event 2: Legacy non-UUID string device_id and admin_id
        await conn.execute(
            """
            INSERT INTO audit_events (
                id, event_time, event_type, principal_type, principal_id,
                device_id, admin_id, user_id, decision, request_id
            ) VALUES (
                $1, NOW(), 'verify', 'device', 'dev_legacy_token',
                'legacy-kiosk-name', 'legacy-admin-string', $2, 'match', 'req-str-dev'
            )
            """,
            uuid.uuid4(),
            user_id,
        )
        print("   -> Inserted Phase 5 test records (users, templates, audit_events with string IDs).")
    finally:
        await conn.close()


async def verify_phase6_data(db_url: str) -> None:
    """Verifies that Phase 6 migration migrated column types and preserved data."""
    conn = await asyncpg.connect(db_url)
    try:
        # Check column types on audit_events
        row = await conn.fetchrow(
            """
            SELECT data_type FROM information_schema.columns 
            WHERE table_name = 'audit_events' AND column_name = 'device_id'
            """
        )
        assert row and row["data_type"] == "uuid", f"Expected uuid, got {row}"

        # Check that legacy string device_id was converted to NULL
        dev_rows = await conn.fetch("SELECT device_id, admin_id, request_id FROM audit_events")
        assert len(dev_rows) == 2, f"Expected 2 audit rows, got {len(dev_rows)}"
        for r in dev_rows:
            assert r["device_id"] is None, f"Expected NULL device_id for legacy string, got {r['device_id']}"
            assert r["admin_id"] is None, f"Expected NULL admin_id for legacy string, got {r['admin_id']}"

        # Verify new tables exist
        tables = await conn.fetch(
            """
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name IN ('admin_users', 'devices', 'pairing_tokens')
            """
        )
        found_tables = {t["table_name"] for t in tables}
        expected = {"admin_users", "devices", "pairing_tokens"}
        assert expected.issubset(found_tables), f"Missing tables: {expected - found_tables}"
        print("   -> Phase 6 verification passed: column types converted to UUID, new tables present.")
    finally:
        await conn.close()


def main():
    admin_url = os.environ.get(
        "FREQID_ADMIN_DB_URL",
        "postgresql://freqid_admin:freqid_admin_dev_password@127.0.0.1:54322/postgres",
    )

    test_db_name = f"freqid_mig_test_{int(time.time())}"
    print(f"Creating throwaway test database: {test_db_name}...")
    asyncio.run(create_db(admin_url, test_db_name))

    test_db_asyncpg_url = f"postgresql+asyncpg://freqid_admin:freqid_admin_dev_password@127.0.0.1:54322/{test_db_name}"
    test_db_sync_url = f"postgresql://freqid_admin:freqid_admin_dev_password@127.0.0.1:54322/{test_db_name}"
    os.environ["FREQID_DATABASE_URL"] = test_db_asyncpg_url

    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    alembic_ini_path = os.path.join(backend_dir, "alembic.ini")
    alembic_cfg = Config(alembic_ini_path)
    alembic_cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))

    try:
        print("1. Testing 'alembic upgrade 750c49748c60' (Phase 5 initial schema)...")
        command.upgrade(alembic_cfg, "750c49748c60")
        print("   -> Phase 5 schema applied successfully.")

        print("2. Populating Phase 5 data (including audit events with string & null IDs)...")
        asyncio.run(insert_phase5_test_data(test_db_sync_url))

        print("3. Testing 'alembic upgrade head' (Phase 6 migration on top of Phase 5 data)...")
        command.upgrade(alembic_cfg, "head")
        print("   -> Upgrade to Phase 6 successful.")

        print("4. Verifying Phase 6 schema and data consistency...")
        asyncio.run(verify_phase6_data(test_db_sync_url))

        print("5. Testing rollback one step 'alembic downgrade -1'...")
        command.downgrade(alembic_cfg, "-1")
        print("   -> Rollback to Phase 5 successful.")

        print("6. Testing re-application 'alembic upgrade head'...")
        command.upgrade(alembic_cfg, "head")
        print("   -> Re-upgrade to head successful.")

        print("\nSUCCESS: All migration checks passed cleanly.")

    finally:
        print(f"Cleaning up throwaway test database {test_db_name}...")
        asyncio.run(drop_db(admin_url, test_db_name))
        print("Cleanup completed.")


if __name__ == "__main__":
    main()
