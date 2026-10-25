# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
routes_admin_devices.py: Administrator device management API: pairing tokens,
device lifecycle (approve, suspend, resume, revoke), scope updates, and telemetry.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import delete, desc, select, update

from freqid_server.api.routes_admin_auth import get_current_admin
from freqid_server.api.schemas import (
    DeviceActionRequest,
    DeviceDetail,
    DeviceSummary,
    DeviceUpdateRequest,
    PairingTokenCreateRequest,
    PairingTokenCreateResponse,
)
from freqid_server.audit.base import AuditEvent
from freqid_server.auth.base import AuthenticatedPrincipal
from freqid_server.auth.permissions import (
    PERM_DEVICE_APPROVE,
    PERM_DEVICE_CREATE_PAIRING,
    PERM_DEVICE_DELETE_REVOKED,
    PERM_DEVICE_LIST,
    PERM_DEVICE_READ,
    PERM_DEVICE_RESUME,
    PERM_DEVICE_REVOKE,
    PERM_DEVICE_SUSPEND,
    PERM_DEVICE_UPDATE_SCOPES,
)
from freqid_server.errors import (
    InsufficientScopeError,
    ValidationError,
)
from freqid_server.storage.models import (
    DeviceHeartbeatOrm,
    DeviceOrm,
    PairingTokenOrm,
)

router = APIRouter(prefix="/v1/admin/devices", tags=["Admin Devices"])


def require_admin_permission(perm: str):
    async def _checker(
        admin: AuthenticatedPrincipal = Depends(get_current_admin),
    ) -> AuthenticatedPrincipal:
        if not admin.has_scope(perm):
            raise InsufficientScopeError(f"Admin lacks required permission: '{perm}'.")
        return admin

    return _checker


@router.post(
    "/pairing-tokens",
    response_model=PairingTokenCreateResponse,
    status_code=201,
    operation_id="admin_create_pairing_token",
)
async def create_pairing_token(
    payload: PairingTokenCreateRequest,
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_DEVICE_CREATE_PAIRING)),
) -> PairingTokenCreateResponse:
    """Provisions a single-use 128-bit device pairing token with short expiry."""
    raw_token = f"FQID-PAIR-{secrets.token_urlsafe(16)}"
    token_h = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=payload.expires_in_minutes)

    session_factory = getattr(request.app.state, "session_factory", None)
    token_id = uuid.uuid4()

    if session_factory:
        async with session_factory() as session:
            row = PairingTokenOrm(
                id=token_id,
                token_hash=token_h,
                expires_at=expires_at,
                created_by=uuid.UUID(admin.principal_id),
                is_used=False,
                name_hint=payload.name_hint,
                location_hint=payload.location_hint,
                scopes_allowed=payload.scopes,
                created_at=now,
            )
            session.add(row)

            # Record audit event
            audit_sink = getattr(request.app.state, "audit_sink", None)
            if audit_sink:
                await audit_sink.emit(
                    AuditEvent(
                        event_type="pairing_token_created",
                        principal_type="admin",
                        decision="enrolled",
                        request_id=request.headers.get("X-Request-ID", str(uuid.uuid4())),
                        principal_id=admin.principal_id,
                        admin_id=admin.principal_id,
                        client_ip=request.client.host if request.client else None,
                    )
                )

            await session.commit()

    return PairingTokenCreateResponse(
        id=str(token_id),
        token=raw_token,
        expires_at=expires_at.isoformat(),
        scopes_allowed=payload.scopes,
    )


@router.get(
    "",
    response_model=list[DeviceSummary],
    operation_id="admin_list_devices",
)
async def list_devices(
    request: Request,
    state: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_DEVICE_LIST)),
) -> list[DeviceSummary]:
    """Lists registered devices with operational status and telemetry."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if not session_factory:
        return []

    async with session_factory() as session:
        stmt = select(DeviceOrm).order_by(desc(DeviceOrm.created_at)).limit(limit)
        if state:
            stmt = stmt.where(DeviceOrm.state == state)
        res = await session.execute(stmt)
        devices = res.scalars().all()

        return [
            DeviceSummary(
                id=str(d.id),
                name=d.name,
                location=d.location,
                state=d.state,
                scopes=list(d.scopes) if isinstance(d.scopes, list) else [],
                key_id=d.key_id,
                software_version=d.software_version,
                last_seen=d.last_seen.isoformat() if d.last_seen else None,
                created_at=d.created_at.isoformat(),
            )
            for d in devices
        ]


@router.get(
    "/{device_id}",
    response_model=DeviceDetail,
    operation_id="admin_get_device",
)
async def get_device(
    device_id: uuid.UUID,
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_DEVICE_READ)),
) -> DeviceDetail:
    """Retrieves full telemetry, audit trace, and recent heartbeats for a device."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if not session_factory:
        raise ValidationError("Database session unavailable.")

    async with session_factory() as session:
        stmt = select(DeviceOrm).where(DeviceOrm.id == device_id)
        res = await session.execute(stmt)
        device = res.scalars().first()

        if not device:
            raise ValidationError(f"Device '{device_id}' not found.")

        # Query recent heartbeats
        hb_stmt = (
            select(DeviceHeartbeatOrm)
            .where(DeviceHeartbeatOrm.device_id == device_id)
            .order_by(desc(DeviceHeartbeatOrm.timestamp))
            .limit(10)
        )
        hb_res = await session.execute(hb_stmt)
        heartbeats = [
            {
                "timestamp": h.timestamp.isoformat(),
                "software_version": h.software_version,
                "camera_ok": h.camera_ok,
                "uptime_seconds": h.uptime_seconds,
                "queued_payloads": h.queued_payloads,
            }
            for h in hb_res.scalars().all()
        ]

        return DeviceDetail(
            id=str(device.id),
            name=device.name,
            location=device.location,
            state=device.state,
            scopes=list(device.scopes) if isinstance(device.scopes, list) else [],
            public_key=device.public_key,
            key_id=device.key_id,
            software_version=device.software_version,
            approved_by=str(device.approved_by) if device.approved_by else None,
            last_seen=device.last_seen.isoformat() if device.last_seen else None,
            revoked_at=device.revoked_at.isoformat() if device.revoked_at else None,
            revocation_reason=device.revocation_reason,
            created_at=device.created_at.isoformat(),
            recent_heartbeats=heartbeats,
        )


@router.post(
    "/{device_id}/approve",
    response_model=dict[str, str],
    operation_id="admin_approve_device",
)
async def approve_device(
    device_id: uuid.UUID,
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_DEVICE_APPROVE)),
) -> dict[str, str]:
    """Approves a pending device into the active operational state."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if not session_factory:
        raise ValidationError("Database session unavailable.")

    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        stmt = (
            update(DeviceOrm)
            .where(DeviceOrm.id == device_id, DeviceOrm.state == "pending")
            .values(
                state="active",
                approved_by=uuid.UUID(admin.principal_id),
                updated_at=now,
            )
        )
        res = await session.execute(stmt)
        if res.rowcount == 0:
            raise ValidationError(f"Device '{device_id}' is not in pending state.")
        await session.commit()

    return {"status": "approved", "device_id": str(device_id)}


@router.post(
    "/{device_id}/suspend",
    response_model=dict[str, str],
    operation_id="admin_suspend_device",
)
async def suspend_device(
    device_id: uuid.UUID,
    request: Request,
    payload: DeviceActionRequest | None = None,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_DEVICE_SUSPEND)),
) -> dict[str, str]:
    """Places an active device under temporary reversible administrative suspension."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if not session_factory:
        raise ValidationError("Database session unavailable.")

    now = datetime.now(timezone.utc)
    reason = (payload.reason if payload else None) or "Administrative suspension"
    async with session_factory() as session:
        stmt = (
            update(DeviceOrm)
            .where(DeviceOrm.id == device_id, DeviceOrm.state == "active")
            .values(
                state="suspended",
                revocation_reason=reason,
                updated_at=now,
            )
        )
        res = await session.execute(stmt)
        if res.rowcount == 0:
            raise ValidationError(f"Device '{device_id}' is not in active state.")
        await session.commit()

    return {"status": "suspended", "device_id": str(device_id)}


@router.post(
    "/{device_id}/resume",
    response_model=dict[str, str],
    operation_id="admin_resume_device",
)
async def resume_device(
    device_id: uuid.UUID,
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_DEVICE_RESUME)),
) -> dict[str, str]:
    """Resumes a suspended device back to the active state."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if not session_factory:
        raise ValidationError("Database session unavailable.")

    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        stmt = (
            update(DeviceOrm)
            .where(DeviceOrm.id == device_id, DeviceOrm.state == "suspended")
            .values(
                state="active",
                revocation_reason=None,
                updated_at=now,
            )
        )
        res = await session.execute(stmt)
        if res.rowcount == 0:
            raise ValidationError(f"Device '{device_id}' is not in suspended state.")
        await session.commit()

    return {"status": "resumed", "device_id": str(device_id)}


@router.post(
    "/{device_id}/revoke",
    response_model=dict[str, str],
    operation_id="admin_revoke_device",
)
async def revoke_device(
    device_id: uuid.UUID,
    request: Request,
    payload: DeviceActionRequest | None = None,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_DEVICE_REVOKE)),
) -> dict[str, str]:
    """Permanently revokes a device (immediate kill). Revoked devices can never return to active."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if not session_factory:
        raise ValidationError("Database session unavailable.")

    now = datetime.now(timezone.utc)
    reason = (payload.reason if payload else None) or "Administrative revocation"
    async with session_factory() as session:
        stmt = (
            update(DeviceOrm)
            .where(DeviceOrm.id == device_id)
            .values(
                state="revoked",
                revoked_at=now,
                revocation_reason=reason,
                updated_at=now,
            )
        )
        res = await session.execute(stmt)
        if res.rowcount == 0:
            raise ValidationError(f"Device '{device_id}' not found.")
        await session.commit()

    return {"status": "revoked", "device_id": str(device_id)}


@router.patch(
    "/{device_id}",
    response_model=dict[str, str],
    operation_id="admin_update_device",
)
async def update_device(
    device_id: uuid.UUID,
    payload: DeviceUpdateRequest,
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_DEVICE_UPDATE_SCOPES)),
) -> dict[str, str]:
    """Updates device metadata, location, or assigned permission scopes."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if not session_factory:
        raise ValidationError("Database session unavailable.")

    updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.location is not None:
        updates["location"] = payload.location
    if payload.scopes is not None:
        updates["scopes"] = payload.scopes

    async with session_factory() as session:
        stmt = update(DeviceOrm).where(DeviceOrm.id == device_id).values(**updates)
        res = await session.execute(stmt)
        if res.rowcount == 0:
            raise ValidationError(f"Device '{device_id}' not found.")
        await session.commit()

    return {"status": "updated", "device_id": str(device_id)}


@router.delete(
    "/{device_id}",
    response_model=dict[str, str],
    operation_id="admin_delete_device",
)
async def delete_revoked_device(
    device_id: uuid.UUID,
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_DEVICE_DELETE_REVOKED)),
) -> dict[str, str]:
    """Purges a device record (permitted only if already revoked)."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if not session_factory:
        raise ValidationError("Database session unavailable.")

    async with session_factory() as session:
        stmt = select(DeviceOrm).where(DeviceOrm.id == device_id)
        res = await session.execute(stmt)
        device = res.scalars().first()

        if not device:
            raise ValidationError(f"Device '{device_id}' not found.")
        if device.state != "revoked":
            raise ValidationError(
                f"Device '{device_id}' must be revoked before deletion (current state: '{device.state}')."
            )

        del_stmt = delete(DeviceOrm).where(DeviceOrm.id == device_id)
        await session.execute(del_stmt)
        await session.commit()

    return {"status": "deleted", "device_id": str(device_id)}
