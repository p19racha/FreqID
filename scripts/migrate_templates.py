#!/usr/bin/env python3
# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
migrate_templates.py: Zero-downtime batch migration CLI for biometric templates from v1 (unrotated) to v2 (cancelable orthogonal rotation).

Reads encrypted templates from PostgreSQL, re-wraps and rotates embeddings to format_version=2,
and writes updated ciphertext and metadata atomically in batches.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
import time
from pathlib import Path

# Add backend/src to path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "backend" / "src"))

from freqid_server.config import load_config
from freqid_server.crypto.envelope import EncryptedTemplateRecord, TemplateEncryptor
from freqid_server.crypto.provider import EnvOrFileKeyProvider
from freqid_server.storage.models import TemplateOrm, UserOrm
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def migrate_templates(
    target_format: int = 2,
    batch_size: int = 100,
    dry_run: bool = False,
    config_path: str | None = None,
) -> None:
    cfg = load_config(config_path=config_path)

    print(f"[*] FreqID Template Migration to Format Version {target_format}")
    print(f"    Database URL: {cfg.database_url.split('@')[-1]}")
    print(f"    Mode: {'DRY RUN (no DB modifications)' if dry_run else 'LIVE MIGRATION'}")

    engine = create_async_engine(cfg.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    key_provider = EnvOrFileKeyProvider(
        key_file_path=cfg.master_key_file or None,
        default_key=None,
        default_key_id=cfg.active_key_id,
    )
    encryptor = TemplateEncryptor(key_provider=key_provider)

    async with session_factory() as session:
        # 1. Total counts by format_version
        stmt_counts = select(
            TemplateOrm.format_version,
            func.count(TemplateOrm.id),
        ).group_by(TemplateOrm.format_version)
        res_counts = await session.execute(stmt_counts)
        counts_by_ver = dict(res_counts.all())

        total = sum(counts_by_ver.values())
        v1_count = counts_by_ver.get(1, 0)
        v2_count = counts_by_ver.get(2, 0)

        print(f"[*] Current template population: total={total}")
        print(f"    Format v1 (Legacy unrotated): {v1_count}")
        print(f"    Format v2 (Rotated O(512)) : {v2_count}")

        if v1_count == 0:
            print("[+] All templates are already at format_version >= 2. Nothing to migrate.")
            await engine.dispose()
            return

        if dry_run:
            print(f"[*] Dry-run complete. {v1_count} templates would be migrated in ~{math.ceil(v1_count / batch_size)} batches.")
            await engine.dispose()
            return

    # 2. Live batch migration
    migrated_count = 0
    start_time = time.perf_counter()

    while True:
        async with session_factory() as session, session.begin():
            stmt = (
                select(TemplateOrm, UserOrm.id)
                .join(UserOrm, TemplateOrm.user_id == UserOrm.id)
                .where(TemplateOrm.format_version < target_format)
                .limit(batch_size)
            )
            rows = (await session.execute(stmt)).all()
            if not rows:
                break

            for tmpl, user_uuid in rows:
                # 1. Decrypt existing record
                rec = EncryptedTemplateRecord(
                    encrypted_blob=tmpl.encrypted_blob,
                    wrapped_data_key=tmpl.wrapped_data_key,
                    nonce=tmpl.nonce,
                    key_id=tmpl.key_id,
                    format_version=tmpl.format_version,
                )
                raw_emb = encryptor.decrypt(
                    record=rec,
                    user_id=str(user_uuid),
                    model_version=tmpl.model_version,
                )

                # 2. Re-encrypt with target format_version (applies orthogonal transformation R)
                new_rec = encryptor.encrypt(
                    embedding=raw_emb,
                    user_id=str(user_uuid),
                    model_version=tmpl.model_version,
                    format_version=target_format,
                )

                # 3. Update database row
                tmpl.encrypted_blob = new_rec.encrypted_blob
                tmpl.wrapped_data_key = new_rec.wrapped_data_key
                tmpl.nonce = new_rec.nonce
                tmpl.key_id = new_rec.key_id
                tmpl.format_version = new_rec.format_version
                tmpl.version += 1

                migrated_count += 1

            print(f"    Migrated batch: {migrated_count}/{v1_count} templates...")

    elapsed = time.perf_counter() - start_time
    print(f"[+] Successfully migrated {migrated_count} templates in {elapsed:.2f}s ({migrated_count / max(1e-5, elapsed):.1f} tmpl/s).")
    await engine.dispose()


def main() -> None:

    parser = argparse.ArgumentParser(description="FreqID Biometric Template Migration Utility")
    parser.add_argument("--target-format", type=int, default=2, help="Target format version (default: 2)")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for DB transactions (default: 100)")
    parser.add_argument("--dry-run", action="store_true", help="Inspect template counts without modifying DB")
    parser.add_argument("--config", help="Path to server YAML configuration file")

    args = parser.parse_args()

    asyncio.run(
        migrate_templates(
            target_format=args.target_format,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            config_path=args.config,
        )
    )


if __name__ == "__main__":
    main()
