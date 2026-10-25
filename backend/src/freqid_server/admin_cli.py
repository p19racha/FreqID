# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
admin_cli.py: Administrative command-line interface for FreqID.
Supports bootstrapping the owner, password resets, account unlocking, and admin management.
Never accepts passwords as command-line arguments to prevent leakage in shell history.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from freqid_server.auth.passwords import hash_password
from freqid_server.config import load_config
from freqid_server.storage.models import AdminUserOrm, AuditEventOrm


def get_db_url() -> str:
    cfg = load_config()
    return cfg.database_url


async def create_owner_cmd(username: str, force: bool = False) -> None:
    db_url = get_db_url()
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        # Check if an active owner already exists
        stmt = select(AdminUserOrm).where(
            AdminUserOrm.role == "owner", AdminUserOrm.is_active == True
        )
        res = await session.execute(stmt)
        existing_owner = res.scalars().first()

        if existing_owner and not force:
            print(
                f"Error: An active owner account '{existing_owner.username}' already exists. "
                "Use --force if you explicitly intend to create an additional owner account.",
                file=sys.stderr,
            )
            await engine.dispose()
            sys.exit(1)

        print(f"Creating owner account: '{username}'")
        pwd1 = getpass.getpass("Enter owner password: ")
        pwd2 = getpass.getpass("Confirm owner password: ")

        if pwd1 != pwd2:
            print("Error: Passwords do not match.", file=sys.stderr)
            await engine.dispose()
            sys.exit(1)

        try:
            pwd_hash = hash_password(pwd1)
        except Exception as e:
            print(f"Error: Password does not meet security requirements: {e}", file=sys.stderr)
            await engine.dispose()
            sys.exit(1)

        now = datetime.now(timezone.utc)
        admin_id = uuid.uuid4()
        new_owner = AdminUserOrm(
            id=admin_id,
            username=username,
            password_hash=pwd_hash,
            role="owner",
            is_active=True,
            failed_logins=0,
            locked_until=None,
            created_at=now,
            updated_at=now,
        )
        session.add(new_owner)

        # Record audit event
        audit = AuditEventOrm(
            id=uuid.uuid4(),
            event_time=now,
            event_type="admin_bootstrapped",
            principal_type="admin",
            principal_id=str(admin_id),
            admin_id=admin_id,
            decision="authenticated",
            request_id=f"cli-create-owner-{int(now.timestamp())}",
        )
        session.add(audit)

        await session.commit()
        print(f"Success: Owner account '{username}' (ID: {admin_id}) successfully created.")

    await engine.dispose()


async def reset_password_cmd(username: str) -> None:
    db_url = get_db_url()
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        stmt = select(AdminUserOrm).where(AdminUserOrm.username == username)
        res = await session.execute(stmt)
        admin = res.scalars().first()

        if not admin:
            print(f"Error: Admin user '{username}' not found.", file=sys.stderr)
            await engine.dispose()
            sys.exit(1)

        pwd1 = getpass.getpass(f"Enter new password for '{username}': ")
        pwd2 = getpass.getpass("Confirm new password: ")

        if pwd1 != pwd2:
            print("Error: Passwords do not match.", file=sys.stderr)
            await engine.dispose()
            sys.exit(1)

        try:
            pwd_hash = hash_password(pwd1)
        except Exception as e:
            print(f"Error: Password does not meet security requirements: {e}", file=sys.stderr)
            await engine.dispose()
            sys.exit(1)

        admin.password_hash = pwd_hash
        admin.failed_logins = 0
        admin.locked_until = None
        admin.updated_at = datetime.now(timezone.utc)

        await session.commit()
        print(f"Success: Password for '{username}' successfully updated.")

    await engine.dispose()


async def unlock_cmd(username: str) -> None:
    db_url = get_db_url()
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        stmt = select(AdminUserOrm).where(AdminUserOrm.username == username)
        res = await session.execute(stmt)
        admin = res.scalars().first()

        if not admin:
            print(f"Error: Admin user '{username}' not found.", file=sys.stderr)
            await engine.dispose()
            sys.exit(1)

        admin.failed_logins = 0
        admin.locked_until = None
        admin.updated_at = datetime.now(timezone.utc)

        await session.commit()
        print(f"Success: Account '{username}' unlocked.")

    await engine.dispose()


async def list_admins_cmd() -> None:
    db_url = get_db_url()
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        stmt = select(AdminUserOrm).order_by(AdminUserOrm.created_at.asc())
        res = await session.execute(stmt)
        admins = res.scalars().all()

        if not admins:
            print("No administrator accounts found.")
            await engine.dispose()
            return

        print(f"{'Username':<20} {'Role':<12} {'Active':<8} {'Failed':<8} {'Locked Until':<25}")
        print("-" * 75)
        for a in admins:
            locked = a.locked_until.isoformat() if a.locked_until else "None"
            print(
                f"{a.username:<20} {a.role:<12} {a.is_active!s:<8} {a.failed_logins:<8} {locked:<25}"
            )

    await engine.dispose()


async def disable_admin_cmd(username: str) -> None:
    db_url = get_db_url()
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        stmt = select(AdminUserOrm).where(AdminUserOrm.username == username)
        res = await session.execute(stmt)
        admin = res.scalars().first()

        if not admin:
            print(f"Error: Admin user '{username}' not found.", file=sys.stderr)
            await engine.dispose()
            sys.exit(1)

        admin.is_active = False
        admin.updated_at = datetime.now(timezone.utc)
        await session.commit()
        print(f"Success: Admin account '{username}' has been disabled.")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="freqid-admin",
        description="FreqID Administrative Management CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create-owner
    p_create = subparsers.add_parser("create-owner", help="Bootstrap initial owner account")
    p_create.add_argument("--username", required=True, help="Username for owner account")
    p_create.add_argument("--force", action="store_true", help="Allow creating additional owner")

    # reset-password
    p_reset = subparsers.add_parser("reset-password", help="Reset password for an admin account")
    p_reset.add_argument("--username", required=True, help="Username of the admin account")

    # unlock
    p_unlock = subparsers.add_parser("unlock", help="Unlock a locked-out admin account")
    p_unlock.add_argument("--username", required=True, help="Username to unlock")

    # list-admins
    subparsers.add_parser("list-admins", help="List all administrator accounts")

    # disable-admin
    p_disable = subparsers.add_parser("disable-admin", help="Disable an admin account")
    p_disable.add_argument("--username", required=True, help="Username to disable")

    args = parser.parse_args()

    if args.command == "create-owner":
        asyncio.run(create_owner_cmd(args.username, force=args.force))
    elif args.command == "reset-password":
        asyncio.run(reset_password_cmd(args.username))
    elif args.command == "unlock":
        asyncio.run(unlock_cmd(args.username))
    elif args.command == "list-admins":
        asyncio.run(list_admins_cmd())
    elif args.command == "disable-admin":
        asyncio.run(disable_admin_cmd(args.username))


if __name__ == "__main__":
    main()
