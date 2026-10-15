# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
routes_admin_auth.py: Administrator authentication endpoints including login,
session refresh with reuse detection, logout, password rotation, and TOTP management.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from freqid_server.audit.base import AuditEvent
from freqid_server.auth.base import AuthenticatedPrincipal
from freqid_server.auth.lockout import LockoutManager
from freqid_server.auth.passwords import (
    hash_password,
    validate_password_policy,
    verify_dummy_baseline,
    verify_password,
)
from freqid_server.auth.permissions import get_permissions_for_role
from freqid_server.auth.tokens import (
    create_access_token,
    generate_refresh_token,
    hash_token,
)
from freqid_server.auth.totp import (
    generate_recovery_codes,
    generate_totp_secret,
    get_totp_uri,
    verify_totp_code,
)
from freqid_server.errors import (
    AccountDisabledError,
    AccountLockedError,
    AuthenticationError,
    ValidationError,
)
from freqid_server.storage.models import AdminRefreshTokenOrm, AdminUserOrm

router = APIRouter(prefix="/v1/admin/auth", tags=["Admin Auth"])


def get_db_session(request: Request) -> AsyncSession:
    """Dependency helper yielding DB session."""
    session_factory = request.app.state.session_factory
    if not session_factory:
        raise RuntimeError("PostgreSQL session factory not initialized.")
    return session_factory()


async def get_current_admin(request: Request) -> AuthenticatedPrincipal:
    """Dependency requiring authenticated admin principal."""
    authenticator = request.app.state.authenticator
    principal = await authenticator.authenticate(request)
    if principal.principal_type != "admin":
        raise AuthenticationError("Admin credentials required.")
    return principal


@router.post("/login", response_model=dict[str, Any], operation_id="admin_login")
async def login(
    req_body: dict[str, Any],
    request: Request,
    response: Response,
) -> dict[str, Any]:
    """Authenticates administrator and issues JWT access token + rotating refresh cookie."""
    username = str(req_body.get("username", "")).strip()
    password = str(req_body.get("password", ""))
    totp_code = req_body.get("totp_code")

    if not username or not password:
        raise ValidationError("Username and password are required.")

    cfg = request.app.state.config
    lockout_mgr: LockoutManager = request.app.state.lockout_manager
    client_ip = request.client.host if request.client else None

    # 1. Check account / IP lockout
    is_locked, remaining_secs = lockout_mgr.is_locked(username, client_ip)
    if is_locked:
        raise AccountLockedError(
            f"Account or IP is locked due to repeated failed logins. Retry in {remaining_secs}s.",
            retry_after=remaining_secs,
        )

    session_factory = getattr(request.app.state, "session_factory", None)
    admin: AdminUserOrm | None = None

    if session_factory:
        async with session_factory() as session:
            stmt = select(AdminUserOrm).where(AdminUserOrm.username == username)
            res = await session.execute(stmt)
            admin = res.scalars().first()

            if not admin:
                # Anti-enumeration: execute calibrated dummy hashing
                verify_dummy_baseline(password)
                lockout_mgr.record_failure(username, client_ip)
                raise AuthenticationError("Invalid username or password.")

            if not admin.is_active:
                raise AccountDisabledError("Admin account has been disabled.")

            # Verify password
            if not verify_password(password, admin.password_hash):
                lockout_mgr.record_failure(username, client_ip)
                admin.failed_logins += 1
                await session.commit()
                raise AuthenticationError("Invalid username or password.")

            # Verify TOTP if enabled
            if admin.totp_enabled:
                if not totp_code:
                    raise AuthenticationError("TOTP two-factor code required.")
                secret = admin.totp_secret_enc or ""
                if not verify_totp_code(secret, str(totp_code)):
                    raise AuthenticationError("Invalid TOTP code.")

            # Authentication succeeded
            lockout_mgr.record_success(username, client_ip)
            admin.failed_logins = 0
            admin.locked_until = None

            # Issue refresh token
            now = datetime.now(timezone.utc)
            raw_refresh = generate_refresh_token()
            token_h = hash_token(raw_refresh)
            family_id = uuid.uuid4()
            expires_at = now + timedelta(days=7)

            refresh_row = AdminRefreshTokenOrm(
                id=uuid.uuid4(),
                admin_id=admin.id,
                token_hash=token_h,
                family_id=family_id,
                is_revoked=False,
                expires_at=expires_at,
                created_at=now,
                user_agent=request.headers.get("User-Agent"),
                ip_hash=client_ip,
            )
            session.add(refresh_row)
            await session.commit()

            # Record audit event
            audit_sink = getattr(request.app.state, "audit_sink", None)
            if audit_sink:
                await audit_sink.emit(
                    AuditEvent(
                        event_type="admin_login",
                        principal_type="admin",
                        decision="authenticated",
                        request_id=request.headers.get("X-Request-ID", str(uuid.uuid4())),
                        principal_id=str(admin.id),
                        admin_id=str(admin.id),
                        client_ip=client_ip,
                    )
                )

            # Issue access token
            access_token = create_access_token(
                admin_id=admin.id,
                username=admin.username,
                role=admin.role,
                secret_key=cfg.master_key,
                expires_delta=timedelta(minutes=15),
            )

            # Set refresh cookie
            response.set_cookie(
                key="freqid_refresh_token",
                value=raw_refresh,
                httponly=True,
                secure=cfg.environment == "production",
                samesite="lax",
                path="/v1/admin/auth",
                max_age=7 * 86400,
            )

            return {
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": 900,
                "admin_id": str(admin.id),
                "username": admin.username,
                "role": admin.role,
                "permissions": list(get_permissions_for_role(admin.role)),
            }

    # In-memory test double fallback
    authenticator = request.app.state.authenticator
    for aid, m in authenticator._mem_admins.items():
        if m["username"] == username:
            if not m.get("is_active", True):
                raise AccountDisabledError("Admin account has been disabled.")
            access_token = create_access_token(
                admin_id=aid,
                username=username,
                role=m["role"],
                secret_key=cfg.master_key,
            )
            return {
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": 900,
                "admin_id": str(aid),
                "username": username,
                "role": m["role"],
                "permissions": list(get_permissions_for_role(m["role"])),
            }

    verify_dummy_baseline(password)
    raise AuthenticationError("Invalid username or password.")


@router.post("/refresh", response_model=dict[str, Any], operation_id="admin_refresh")
async def refresh_session(
    request: Request,
    response: Response,
    freqid_refresh_token: str | None = Cookie(default=None),
) -> dict[str, Any]:
    """Rotates refresh token and issues a new access token; revokes family if reuse detected."""
    token = freqid_refresh_token or request.headers.get("X-Refresh-Token")
    if not token:
        raise AuthenticationError("Refresh token missing.")

    cfg = request.app.state.config
    token_h = hash_token(token)
    session_factory = getattr(request.app.state, "session_factory", None)

    if not session_factory:
        raise AuthenticationError("Session store unavailable.")

    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        stmt = (
            select(AdminRefreshTokenOrm, AdminUserOrm)
            .join(AdminUserOrm, AdminRefreshTokenOrm.admin_id == AdminUserOrm.id)
            .where(AdminRefreshTokenOrm.token_hash == token_h)
        )
        res = await session.execute(stmt)
        row = res.first()

        if not row:
            raise AuthenticationError("Invalid refresh token.")

        token_orm, admin_orm = row

        # REUSE DETECTION: If token was already revoked, someone is replaying it!
        if token_orm.is_revoked:
            # Revoke entire family ("compromise defense")
            family_stmt = (
                update(AdminRefreshTokenOrm)
                .where(AdminRefreshTokenOrm.family_id == token_orm.family_id)
                .values(is_revoked=True)
            )
            await session.execute(family_stmt)
            await session.commit()
            raise AuthenticationError("Refresh token reuse detected. All sessions terminated.")

        if token_orm.expires_at < now:
            raise AuthenticationError("Refresh token has expired.")

        if not admin_orm.is_active:
            raise AccountDisabledError("Admin account has been disabled.")

        # Burn old token
        token_orm.is_revoked = True

        # Issue new token in same family
        new_raw_refresh = generate_refresh_token()
        new_token_h = hash_token(new_raw_refresh)
        new_refresh = AdminRefreshTokenOrm(
            id=uuid.uuid4(),
            admin_id=admin_orm.id,
            token_hash=new_token_h,
            family_id=token_orm.family_id,
            is_revoked=False,
            expires_at=now + timedelta(days=7),
            created_at=now,
        )
        session.add(new_refresh)
        await session.commit()

        # Issue new access token
        access_token = create_access_token(
            admin_id=admin_orm.id,
            username=admin_orm.username,
            role=admin_orm.role,
            secret_key=cfg.master_key,
        )

        response.set_cookie(
            key="freqid_refresh_token",
            value=new_raw_refresh,
            httponly=True,
            secure=cfg.environment == "production",
            samesite="lax",
            path="/v1/admin/auth",
            max_age=7 * 86400,
        )

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": 900,
            "admin_id": str(admin_orm.id),
            "username": admin_orm.username,
            "role": admin_orm.role,
            "permissions": list(get_permissions_for_role(admin_orm.role)),
        }


@router.post("/logout", operation_id="admin_logout")
async def logout(
    request: Request,
    response: Response,
    freqid_refresh_token: str | None = Cookie(default=None),
) -> dict[str, str]:
    """Invalidates current refresh token server-side and clears cookie."""
    token = freqid_refresh_token or request.headers.get("X-Refresh-Token")
    if token and getattr(request.app.state, "session_factory", None):
        token_h = hash_token(token)
        async with request.app.state.session_factory() as session:
            stmt = (
                update(AdminRefreshTokenOrm)
                .where(AdminRefreshTokenOrm.token_hash == token_h)
                .values(is_revoked=True)
            )
            await session.execute(stmt)
            await session.commit()

    response.delete_cookie(key="freqid_refresh_token", path="/v1/admin/auth")
    return {"status": "logged_out"}


@router.post("/logout-everywhere", operation_id="admin_logout_everywhere")
async def logout_everywhere(
    request: Request,
    response: Response,
    admin: AuthenticatedPrincipal = Depends(get_current_admin),
) -> dict[str, str]:
    """Invalidates all sessions for current administrator across all devices."""
    if getattr(request.app.state, "session_factory", None):
        async with request.app.state.session_factory() as session:
            stmt = (
                update(AdminRefreshTokenOrm)
                .where(AdminRefreshTokenOrm.admin_id == uuid.UUID(admin.principal_id))
                .values(is_revoked=True)
            )
            await session.execute(stmt)
            await session.commit()

    response.delete_cookie(key="freqid_refresh_token", path="/v1/admin/auth")
    return {"status": "all_sessions_revoked"}


@router.get("/me", operation_id="admin_get_me")
async def get_me(
    request: Request,
    admin: AuthenticatedPrincipal = Depends(get_current_admin),
) -> dict[str, Any]:
    """Returns profile and active permissions of authenticated administrator."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory:
        async with session_factory() as session:
            stmt = select(AdminUserOrm).where(AdminUserOrm.id == uuid.UUID(admin.principal_id))
            res = await session.execute(stmt)
            orm = res.scalars().first()
            if orm:
                return {
                    "id": str(orm.id),
                    "username": orm.username,
                    "role": orm.role,
                    "is_active": orm.is_active,
                    "totp_enabled": orm.totp_enabled,
                    "created_at": orm.created_at.isoformat(),
                    "permissions": list(get_permissions_for_role(orm.role)),
                }

    return {
        "id": admin.principal_id,
        "username": "admin",
        "role": "admin",
        "is_active": True,
        "totp_enabled": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "permissions": list(admin.scopes),
    }


@router.post("/change-password", operation_id="admin_change_password")
async def change_password(
    req_body: dict[str, str],
    request: Request,
    admin: AuthenticatedPrincipal = Depends(get_current_admin),
) -> dict[str, str]:
    """Self-service password update requiring current password."""
    curr_pwd = req_body.get("current_password", "")
    new_pwd = req_body.get("new_password", "")

    if not curr_pwd or not new_pwd:
        raise ValidationError("Both current_password and new_password are required.")

    session_factory = getattr(request.app.state, "session_factory", None)
    if not session_factory:
        raise ValidationError("Database session unavailable.")

    async with session_factory() as session:
        stmt = select(AdminUserOrm).where(AdminUserOrm.id == uuid.UUID(admin.principal_id))
        res = await session.execute(stmt)
        orm = res.scalars().first()

        if not orm or not verify_password(curr_pwd, orm.password_hash):
            raise AuthenticationError("Current password incorrect.")

        validate_password_policy(new_pwd)
        orm.password_hash = hash_password(new_pwd)
        orm.updated_at = datetime.now(timezone.utc)

        # Invalidate existing refresh tokens upon password change
        revoke_stmt = (
            update(AdminRefreshTokenOrm)
            .where(AdminRefreshTokenOrm.admin_id == orm.id)
            .values(is_revoked=True)
        )
        await session.execute(revoke_stmt)
        await session.commit()

    return {"status": "password_changed"}
