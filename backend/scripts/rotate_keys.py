#!/usr/bin/env python3
# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
rotate_keys.py: Zero-downtime key rotation re-wrapping DEKs without decrypting biometrics.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

# Ensure backend/src is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from freqid_server.crypto.provider import EnvOrFileKeyProvider
from freqid_server.storage.models import TemplateOrm


async def rotate_keys(
    db_url: str,
    new_key_id: str,
    batch_size: int = 500,
    dry_run: bool = False,
    key_provider: EnvOrFileKeyProvider | None = None,
) -> int:
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = key_provider or EnvOrFileKeyProvider()

    # Verify target key is available
    _ = provider.get_key(new_key_id)

    print("=" * 70)
    print("FreqID Key Rotation Tool")
    print(f"Target Master Key ID: {new_key_id}")
    print(f"Mode: {'DRY RUN' if dry_run else 'ACTIVE ROTATION'}")
    print("=" * 70)

    t0 = time.perf_counter()
    rotated_count = 0

    async with session_factory() as session:
        while True:
            # Resumable: always queries records with old key_id
            stmt = select(TemplateOrm).where(TemplateOrm.key_id != new_key_id).limit(batch_size)
            res = await session.execute(stmt)
            batch = res.scalars().all()
            if not batch:
                break

            if not dry_run:
                for tmpl in batch:
                    # 1. Unwrap DEK using old key
                    dek = provider.unwrap_key(tmpl.wrapped_data_key, tmpl.key_id)
                    # 2. Re-wrap DEK using new master key
                    new_wrapped_dek = provider.wrap_key(dek, new_key_id)
                    # 3. Update record without touching encrypted_blob
                    tmpl.wrapped_data_key = new_wrapped_dek
                    tmpl.key_id = new_key_id
                await session.commit()
            else:
                for tmpl in batch:
                    dek = provider.unwrap_key(tmpl.wrapped_data_key, tmpl.key_id)
                    _ = provider.wrap_key(dek, new_key_id)

            rotated_count += len(batch)
            print(f"Processed {rotated_count} records...")

    t1 = time.perf_counter()
    elapsed = t1 - t0
    qps = rotated_count / elapsed if elapsed > 0 else float("inf")

    print("\nRotation Summary:")
    print(f"Total Records Rotated: {rotated_count}")
    print(f"Total Duration:        {elapsed:.3f} s")
    print(f"Throughput:            {qps:.1f} records/s")
    print("=" * 70)

    await engine.dispose()
    return rotated_count


def main():
    parser = argparse.ArgumentParser(description="FreqID Master Key Rotation Utility")
    parser.add_argument(
        "--new-key-id", type=str, required=True, help="Active master key ID to re-wrap towards"
    )
    parser.add_argument(
        "--batch-size", type=int, default=500, help="Batch commit size (default: 500)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate without committing DB changes"
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=os.environ.get(
            "FREQID_DATABASE_URL",
            "postgresql+asyncpg://freqid_admin:freqid_admin_dev_password@127.0.0.1:54322/freqid",
        ),
    )
    args = parser.parse_args()

    asyncio.run(rotate_keys(args.db_url, args.new_key_id, args.batch_size, args.dry_run))


if __name__ == "__main__":
    main()
