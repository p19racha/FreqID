#!/usr/bin/env python3
# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
verify_audit_chain.py: Verifies cryptographic tamper-evidence hash chain over audit_events.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys

# Ensure backend/src is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from freqid_server.storage.models import AuditEventOrm


async def verify_chain(db_url: str) -> bool:
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    print("Verifying audit hash chain integrity...")
    last_hash = "GENESIS"
    verified_count = 0

    async with session_factory() as session:
        stmt = (
            select(AuditEventOrm)
            .where(AuditEventOrm.chain_hash.isnot(None))
            .order_by(AuditEventOrm.event_time.asc(), AuditEventOrm.id.asc())
        )
        res = await session.execute(stmt)
        events = res.scalars().all()

        if not events:
            print("No chained audit records found.")
            await engine.dispose()
            return True

        for idx, e in enumerate(events):
            expected_input = (
                f"{last_hash}:"
                f"{e.event_time.isoformat()}:{e.event_type}:"
                f"{e.principal_id}:{e.decision}:{e.request_id}"
            )
            computed_hash = hashlib.sha256(expected_input.encode("utf-8")).hexdigest()

            if computed_hash != e.chain_hash:
                print(
                    f"TAMPER DETECTED at event index {idx} (ID: {e.id})!\n"
                    f"  Expected hash: {computed_hash}\n"
                    f"  Found hash:    {e.chain_hash}"
                )
                await engine.dispose()
                return False

            last_hash = computed_hash
            verified_count += 1

    await engine.dispose()
    print(f"SUCCESS: Verified {verified_count} audit event records. Chain integrity intact.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Audit Hash Chain Integrity Verifier")
    parser.add_argument(
        "--db-url",
        type=str,
        default=os.environ.get(
            "FREQID_DATABASE_URL",
            "postgresql+asyncpg://freqid_admin:freqid_admin_dev_password@127.0.0.1:54322/freqid",
        ),
    )
    args = parser.parse_args()

    success = asyncio.run(verify_chain(args.db_url))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
