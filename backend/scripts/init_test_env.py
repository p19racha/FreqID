#!/usr/bin/env python3
# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
init_test_env.py: Bootstraps the test environment for CI and local test execution.

1. Generates synthetic PartialFace ONNX and PyTorch checkpoints if missing.
2. If PostgreSQL is reachable at FREQID_DATABASE_URL:
   - Provisions test database roles (freqid_app, freqid_maint).
   - Runs Alembic migrations to head.
   - Enforces least-privilege table permissions (e.g. append-only audit_events).
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

# Add core/src and backend/src to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CORE_SRC = REPO_ROOT / "core" / "src"
BACKEND_SRC = REPO_ROOT / "backend" / "src"

for p in (CORE_SRC, BACKEND_SRC):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def ensure_test_checkpoints() -> None:
    """Creates synthetic IR_18 ONNX and PyTorch checkpoints for test execution."""
    ckpt_dir = REPO_ROOT / "research" / "outputs" / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    onnx_path = ckpt_dir / "partialface_ir_18.onnx"
    pth_path = ckpt_dir / "partialface_ir_18_epoch5.pth"

    if onnx_path.exists() and pth_path.exists():
        print(f"[i] Test checkpoints already exist at {ckpt_dir}")
        return

    print("[*] Generating synthetic PartialFace test checkpoints...")
    try:
        import torch
        from freqid_core.export_onnx import export_to_onnx
        from freqid_core.model import IR_18_Partial

        # Instantiate lightweight IR_18 model with deterministic seed
        torch.manual_seed(42)
        model = IR_18_Partial(input_channel=27, embedding_dim=512)
        model.eval()

        if not pth_path.exists():
            torch.save({"backbone": model.state_dict()}, str(pth_path))
            print(f"[+] Saved PyTorch test checkpoint: {pth_path}")

        if not onnx_path.exists():
            export_to_onnx(model, str(onnx_path), opset_version=14, dynamic_batch=True)
            print(f"[+] Exported ONNX test checkpoint: {onnx_path}")

    except Exception as e:
        print(f"[!] Warning: Could not generate synthetic checkpoints: {e}", file=sys.stderr)


async def init_postgres_db(admin_url: str) -> bool:
    """Provisions roles, applies Alembic migrations, and configures table grants."""
    try:
        import asyncpg
    except ImportError:
        print("[!] asyncpg not installed, skipping database initialization")
        return False

    # Extract clean connection params from URL
    # postgresql+asyncpg://user:pass@host:port/dbname -> postgresql://user:pass@host:port/dbname
    clean_url = admin_url.replace("postgresql+asyncpg://", "postgresql://")

    # Retry connection for up to 15 seconds (waiting for container readiness)
    conn = None
    for attempt in range(15):
        try:
            conn = await asyncpg.connect(clean_url)
            break
        except Exception:
            time.sleep(1)

    if conn is None:
        print(f"[!] Could not connect to PostgreSQL at {clean_url} after 15s; skipping DB init.")
        return False

    print("[+] Connected to PostgreSQL. Provisioning roles and schema...")
    try:
        # 1. Create freqid_app and freqid_maint roles if missing
        await conn.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'freqid_app') THEN
                    CREATE ROLE freqid_app WITH LOGIN PASSWORD 'freqid_app_dev_secret';
                END IF;
                IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'freqid_maint') THEN
                    CREATE ROLE freqid_maint WITH LOGIN PASSWORD 'freqid_maint_dev_secret';
                END IF;
            END
            $$;
            GRANT USAGE ON SCHEMA public TO freqid_app;
            GRANT USAGE ON SCHEMA public TO freqid_maint;
            """
        )
        print("[+] Test database roles verified.")
    finally:
        await conn.close()

    # 2. Run Alembic migrations to head
    backend_dir = REPO_ROOT / "backend"
    alembic_ini = backend_dir / "alembic.ini"

    try:
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config(str(alembic_ini))
        alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
        # Force admin URL for migrations
        os.environ["FREQID_DATABASE_URL"] = admin_url

        print("[*] Applying Alembic schema migrations...")
        command.upgrade(alembic_cfg, "head")
        print("[+] Alembic migrations applied successfully.")
    except Exception as e:
        print(f"[-] Error running Alembic migrations: {e}", file=sys.stderr)
        return False

    # 3. Apply least-privilege table permissions to roles
    conn = await asyncpg.connect(clean_url)
    try:
        await conn.execute(
            """
            GRANT USAGE ON SCHEMA public TO freqid_app, freqid_maint;
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE users, templates, enrollment_sessions, admin_users, admin_refresh_tokens, devices, pairing_tokens TO freqid_app;
            GRANT SELECT, INSERT ON TABLE audit_events, device_heartbeats TO freqid_app;
            GRANT SELECT, UPDATE ON TABLE system_settings TO freqid_app;
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO freqid_app;

            GRANT SELECT, DELETE ON TABLE audit_events, device_heartbeats, pairing_tokens TO freqid_maint;
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO freqid_maint;

            REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_events FROM freqid_app;
            """
        )
        print("[+] Least-privilege table permissions configured.")
    finally:
        await conn.close()

    return True


def main() -> int:
    ensure_test_checkpoints()

    admin_db_url = os.environ.get(
        "FREQID_DATABASE_URL",
        os.environ.get(
            "FREQID_TEST_ADMIN_DB_URL",
            "postgresql+asyncpg://freqid_admin:freqid_admin_dev_password@127.0.0.1:54322/freqid",
        ),
    )

    try:
        success = asyncio.run(init_postgres_db(admin_db_url))
        if success:
            print("[+] Test environment initialization complete.")
    except Exception as e:
        print(f"[!] Notice: Database init encountered error: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
