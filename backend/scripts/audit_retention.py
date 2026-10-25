#!/usr/bin/env python3
# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
audit_retention.py: Prunes expired audit events older than configured retention period.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

# Ensure backend/src is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from freqid_server.storage.models import AuditEventOrm


async def run_retention(db_url: str, retention_days: int, dry_run: bool) -> int:
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    cutoff_time = datetime.now(timezone.utc) - timedelta(days=retention_days)
    print(f"Audit Retention Policy: {retention_days} days (Cutoff: {cutoff_time.isoformat()})")
    print(f"Mode: {'DRY RUN' if dry_run else 'ACTIVE PURGE'}")

    async with session_factory() as session:
        # 1. Count eligible records
        count_stmt = (
            select(func.count())
            .select_from(AuditEventOrm)
            .where(AuditEventOrm.event_time < cutoff_time)
        )
        res_count = await session.execute(count_stmt)
        eligible_count = int(res_count.scalar_one())

        print(f"Records older than {retention_days} days: {eligible_count}")

        if eligible_count == 0 or dry_run:
            await engine.dispose()
            return eligible_count

        # 2. Execute deletion
        del_stmt = delete(AuditEventOrm).where(AuditEventOrm.event_time < cutoff_time)
        await session.execute(del_stmt)
        await session.commit()

        print(f"SUCCESS: Permanently pruned {eligible_count} expired audit event records.")

    await engine.dispose()
    return eligible_count


def main():
    parser = argparse.ArgumentParser(description="Audit Retention Pruner")
    parser.add_argument(
        "--days", type=int, default=90, help="Retention period in days (default: 90)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report eligible records without deleting"
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=os.environ.get(
            "FREQID_MAINT_DB_URL",
            "postgresql+asyncpg://freqid_maint:freqid_maint_dev_secret@127.0.0.1:54322/freqid",
        ),
        help="Database connection URL with maintenance privileges",
    )
    args = parser.parse_args()

    asyncio.run(run_retention(args.db_url, args.days, args.dry_run))


if __name__ == "__main__":
    main()
