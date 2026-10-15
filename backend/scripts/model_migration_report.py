#!/usr/bin/env python3
# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
model_migration_report.py: Analyzes template model version distribution and reports identities requiring re-enrollment.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

# Ensure backend/src is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from freqid_server.storage.models import TemplateOrm


async def generate_report(db_url: str, active_model_version: str):
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    print("=" * 70)
    print("FreqID Model Version Migration Report")
    print(f"Active Server Model Version: {active_model_version}")
    print("=" * 70)

    async with session_factory() as session:
        # Group by model version
        stmt = (
            select(TemplateOrm.model_version, func.count(TemplateOrm.id))
            .group_by(TemplateOrm.model_version)
        )
        res = await session.execute(stmt)
        breakdown = dict(res.all())

        total = sum(breakdown.values())
        compatible = breakdown.get(active_model_version, 0)
        outdated = total - compatible

        print(f"Total Enrolled Templates:      {total}")
        print(f"Compatible (Ready for Match):  {compatible}")
        print(f"Needs Re-enrollment:           {outdated}")
        print("-" * 70)
        print("Model Version Breakdown:")
        for m_ver, count in breakdown.items():
            status_flag = "ACTIVE" if m_ver == active_model_version else "OUTDATED (RE-ENROLL REQUIRED)"
            print(f"  - {m_ver:<20}: {count:>6} templates [{status_flag}]")
        print("=" * 70)

        if outdated > 0:
            print(
                "\nNOTE: Raw samples and images are never stored in FreqID. Templates from older "
                "models cannot be automatically converted to newer neural representations.\n"
                "Affected subjects must re-enroll via their client terminal."
            )

    await engine.dispose()
    return total, compatible, outdated


def main():
    parser = argparse.ArgumentParser(description="FreqID Model Version Migration Report")
    parser.add_argument(
        "--active-model",
        type=str,
        default=os.environ.get("FREQID_MODEL_VERSION", "v1.0-ir18"),
        help="Active model version identifier",
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

    asyncio.run(generate_report(args.db_url, args.active_model))


if __name__ == "__main__":
    main()
