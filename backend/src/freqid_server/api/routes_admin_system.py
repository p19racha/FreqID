# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
routes_admin_system.py: Admin accounts, audit log query/export, settings, and telemetry.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from freqid_server.api.routes_admin_auth import get_current_admin
from freqid_server.api.schemas import (
    AdminCreateRequest,
    AdminSummary,
    AdminUpdateRequest,
    AuditQueryResponse,
    SystemSettingsResponse,
    SystemSettingsUpdateRequest,
    SystemStatusResponse,
    SecurityStatusResponse,
)
from freqid_server.audit.base import AuditEvent
from freqid_server.auth.base import AuthenticatedPrincipal
from freqid_server.auth.passwords import hash_password, validate_password_policy
from freqid_server.auth.permissions import (
    PERM_ADMIN_CREATE,
    PERM_ADMIN_DISABLE,
    PERM_ADMIN_LIST,
    PERM_ADMIN_UNLOCK,
    PERM_ADMIN_UPDATE_ROLE,
    PERM_AUDIT_EXPORT_CSV,
    PERM_AUDIT_READ,
    PERM_SETTINGS_READ,
    PERM_SETTINGS_UPDATE,
    PERM_SYSTEM_STATUS,
)
from freqid_server.errors import (
    AuthenticationError,
    InsufficientScopeError,
    ValidationError,
)
from freqid_server.storage.models import (
    AdminUserOrm,
    AuditEventOrm,
    DeviceOrm,
    SystemSettingOrm,
)

router = APIRouter(prefix="/v1/admin", tags=["Admin System"])


def require_admin_permission(perm: str):
    async def _checker(admin: AuthenticatedPrincipal = Depends(get_current_admin)) -> AuthenticatedPrincipal:
        if not admin.has_scope(perm):
            raise InsufficientScopeError(f"Admin lacks required permission: '{perm}'.")
        return admin
    return _checker


# -------------------------------------------------------------------------
# Admin User Management (Owner Only)
# -------------------------------------------------------------------------

@router.get("/admins", response_model=list[AdminSummary], operation_id="admin_list_admins")
async def list_admins(
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_ADMIN_LIST)),
) -> list[AdminSummary]:
    """Lists all administrator accounts."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if not session_factory:
        return []

    async with session_factory() as session:
        stmt = select(AdminUserOrm).order_by(AdminUserOrm.created_at.asc())
        res = await session.execute(stmt)
        admins = res.scalars().all()
        return [
            AdminSummary(
                id=str(a.id),
                username=a.username,
                role=a.role,
                is_active=a.is_active,
                failed_logins=a.failed_logins,
                locked_until=a.locked_until.isoformat() if a.locked_until else None,
                created_at=a.created_at.isoformat(),
            )
            for a in admins
        ]


@router.post("/admins", response_model=AdminSummary, status_code=201, operation_id="admin_create_admin")
async def create_admin(
    payload: AdminCreateRequest,
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_ADMIN_CREATE)),
) -> AdminSummary:
    """Creates a new administrator account (Owner only)."""
    username = payload.username.strip()
    role = payload.role.strip()

    if role not in ("owner", "admin", "operator", "auditor"):
        raise ValidationError(f"Invalid role '{role}'. Allowed: owner, admin, operator, auditor.")

    validate_password_policy(payload.password)
    pwd_h = hash_password(payload.password)

    session_factory = getattr(request.app.state, "session_factory", None)
    if not session_factory:
        raise ValidationError("Database session unavailable.")

    now = datetime.now(timezone.utc)
    new_id = uuid.uuid4()
    async with session_factory() as session:
        stmt = select(AdminUserOrm).where(AdminUserOrm.username == username)
        res = await session.execute(stmt)
        if res.scalars().first():
            raise ValidationError(f"Administrator with username '{username}' already exists.")

        new_admin = AdminUserOrm(
            id=new_id,
            username=username,
            password_hash=pwd_h,
            role=role,
            is_active=True,
            failed_logins=0,
            locked_until=None,
            created_at=now,
            updated_at=now,
        )
        session.add(new_admin)
        await session.commit()

        return AdminSummary(
            id=str(new_id),
            username=username,
            role=role,
            is_active=True,
            failed_logins=0,
            locked_until=None,
            created_at=now.isoformat(),
        )


@router.patch("/admins/{admin_id}", response_model=dict[str, str], operation_id="admin_update_admin")
async def update_admin(
    admin_id: uuid.UUID,
    payload: AdminUpdateRequest,
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_ADMIN_UPDATE_ROLE)),
) -> dict[str, str]:
    """Updates role or active status of an admin account (Owner only)."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if not session_factory:
        raise ValidationError("Database session unavailable.")

    updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if payload.role is not None:
        if payload.role not in ("owner", "admin", "operator", "auditor"):
            raise ValidationError(f"Invalid role '{payload.role}'.")
        updates["role"] = payload.role
    if payload.is_active is not None:
        updates["is_active"] = payload.is_active

    async with session_factory() as session:
        stmt = update(AdminUserOrm).where(AdminUserOrm.id == admin_id).values(**updates)
        res = await session.execute(stmt)
        if res.rowcount == 0:
            raise ValidationError(f"Admin '{admin_id}' not found.")
        await session.commit()

    return {"status": "updated", "admin_id": str(admin_id)}


@router.post("/admins/{admin_id}/unlock", response_model=dict[str, str], operation_id="admin_unlock_admin")
async def unlock_admin(
    admin_id: uuid.UUID,
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_ADMIN_UNLOCK)),
) -> dict[str, str]:
    """Clears failed login lockout on an admin account (Owner only)."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if not session_factory:
        raise ValidationError("Database session unavailable.")

    async with session_factory() as session:
        stmt = (
            update(AdminUserOrm)
            .where(AdminUserOrm.id == admin_id)
            .values(
                failed_logins=0,
                locked_until=None,
                updated_at=datetime.now(timezone.utc),
            )
        )
        res = await session.execute(stmt)
        if res.rowcount == 0:
            raise ValidationError(f"Admin '{admin_id}' not found.")
        await session.commit()

    return {"status": "unlocked", "admin_id": str(admin_id)}


# -------------------------------------------------------------------------
# Audit Querying and Export
# -------------------------------------------------------------------------

@router.get("/audit", response_model=AuditQueryResponse, operation_id="admin_query_audit")
async def query_audit(
    request: Request,
    event_type: str | None = Query(default=None),
    decision: str | None = Query(default=None),
    device_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_AUDIT_READ)),
) -> AuditQueryResponse:
    """Queries audit events with optional filtering by event type, decision, or device."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if not session_factory:
        return AuditQueryResponse(items=[], total=0, limit=limit)

    async with session_factory() as session:
        stmt = select(AuditEventOrm).order_by(desc(AuditEventOrm.event_time)).limit(limit)
        if event_type:
            stmt = stmt.where(AuditEventOrm.event_type == event_type)
        if decision:
            stmt = stmt.where(AuditEventOrm.decision == decision)
        if device_id:
            stmt = stmt.where(AuditEventOrm.device_id == device_id)

        res = await session.execute(stmt)
        rows = res.scalars().all()

        items = [
            {
                "id": str(r.id),
                "event_time": r.event_time.isoformat(),
                "event_type": r.event_type,
                "principal_type": r.principal_type,
                "principal_id": r.principal_id,
                "device_id": str(r.device_id) if r.device_id else None,
                "decision": r.decision,
                "score_bucket": r.score_bucket,
                "request_id": r.request_id,
                "model_version": r.model_version,
            }
            for r in rows
        ]
        return AuditQueryResponse(items=items, total=len(items), limit=limit)


@router.get("/audit/export", operation_id="admin_export_audit_csv")
async def export_audit_csv(
    request: Request,
    limit: int = Query(default=1000, ge=1, le=10000),
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_AUDIT_EXPORT_CSV)),
) -> StreamingResponse:
    """Streams audit events as a downloadable CSV file."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if not session_factory:
        raise ValidationError("Database session unavailable.")

    async with session_factory() as session:
        stmt = select(AuditEventOrm).order_by(desc(AuditEventOrm.event_time)).limit(limit)
        res = await session.execute(stmt)
        rows = res.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "event_time",
        "event_type",
        "principal_type",
        "principal_id",
        "device_id",
        "decision",
        "score_bucket",
        "request_id",
        "model_version",
    ])

    for r in rows:
        writer.writerow([
            r.event_time.isoformat(),
            r.event_type,
            r.principal_type,
            r.principal_id or "",
            str(r.device_id) if r.device_id else "",
            r.decision,
            r.score_bucket or "",
            r.request_id,
            r.model_version or "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=freqid_audit_export.csv"},
    )


# -------------------------------------------------------------------------
# Settings and System Status
# -------------------------------------------------------------------------

@router.get("/settings", response_model=SystemSettingsResponse, operation_id="admin_get_settings")
async def get_settings(
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_SETTINGS_READ)),
) -> SystemSettingsResponse:
    """Reads system configuration settings."""
    cfg = request.app.state.config
    settings_dict = {
        "decision_threshold": cfg.decision_threshold,
        "identify_score_floor": cfg.identify_score_floor,
        "enroll_duplicate_check_policy": cfg.enroll_duplicate_check_policy,
        "enroll_duplicate_threshold": cfg.enroll_duplicate_threshold,
        "rate_limit_per_minute": cfg.rate_limit_per_minute,
        "max_enrolled_users": cfg.max_enrolled_users,
    }
    return SystemSettingsResponse(settings=settings_dict)


@router.put("/settings", response_model=dict[str, str], operation_id="admin_update_settings")
async def update_settings(
    payload: SystemSettingsUpdateRequest,
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_SETTINGS_UPDATE)),
) -> dict[str, str]:
    """Updates runtime system settings with validation and audit logging (Owner only)."""
    cfg = request.app.state.config
    updates = payload.settings

    # Validate settings ranges
    if "decision_threshold" in updates:
        val = float(updates["decision_threshold"])
        if not (0.0 <= val <= 1.0):
            raise ValidationError("decision_threshold must be between 0.0 and 1.0.")
        cfg.decision_threshold = val

    if "enroll_duplicate_check_policy" in updates:
        pol = str(updates["enroll_duplicate_check_policy"]).lower()
        if pol not in ("disabled", "warn", "block"):
            raise ValidationError("enroll_duplicate_check_policy must be 'disabled', 'warn', or 'block'.")
        cfg.enroll_duplicate_check_policy = pol

    # Record audit event
    audit_sink = getattr(request.app.state, "audit_sink", None)
    if audit_sink:
        await audit_sink.emit(
            AuditEvent(
                event_type="settings_updated",
                principal_type="admin",
                decision="updated",
                request_id=request.headers.get("X-Request-ID", str(uuid.uuid4())),
                principal_id=admin.principal_id,
                admin_id=admin.principal_id,
                client_ip=request.client.host if request.client else None,
            )
        )

    return {"status": "settings_updated"}


@router.get("/system/status", response_model=SystemStatusResponse, operation_id="admin_system_status")
async def get_system_status(
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_SYSTEM_STATUS)),
) -> SystemStatusResponse:
    """Returns telemetry on model version, gallery size, queue health, and device counts."""
    cfg = request.app.state.config
    gallery = getattr(request.app.state, "gallery", None)
    gallery_size = len(gallery.identities) if gallery and hasattr(gallery, "identities") else 0

    inference_service = getattr(request.app.state, "inference", None)
    queue_depth = 0
    if inference_service and hasattr(inference_service, "_task_queue"):
        queue_depth = inference_service._task_queue.qsize()

    audit_sink = getattr(request.app.state, "audit_sink", None)
    audit_queue_size = audit_sink._queue.qsize() if audit_sink and hasattr(audit_sink, "_queue") else 0

    session_factory = getattr(request.app.state, "session_factory", None)
    device_counts = {"active": 0, "pending": 0, "suspended": 0, "revoked": 0}
    devices_offline = 0

    if session_factory:
        async with session_factory() as session:
            stmt = select(DeviceOrm.state, func.count(DeviceOrm.id)).group_by(DeviceOrm.state)
            res = await session.execute(stmt)
            for state_val, cnt in res.all():
                device_counts[state_val] = cnt

    return SystemStatusResponse(
        model_version=cfg.model_version,
        gallery_size=gallery_size,
        queue_depth=queue_depth,
        device_counts=device_counts,
        devices_offline=devices_offline,
        audit_queue_size=audit_queue_size,
    )


@router.get("/security/status", response_model=SecurityStatusResponse, operation_id="admin_security_status")
async def get_security_status(
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_SYSTEM_STATUS)),
) -> SecurityStatusResponse:
    """Returns active cryptographic security posture, template protection state, and anomaly detector telemetry."""
    cfg = request.app.state.config
    key_provider = getattr(request.app.state, "key_provider", None)
    active_key_id = key_provider.current_key_id() if key_provider else (cfg.active_key_id or "unknown")

    pub_hex = ""
    if key_provider is not None:
        try:
            _, pub_bytes = key_provider.get_payload_keypair(active_key_id)
            pub_hex = pub_bytes.hex()
        except (KeyError, ValueError):
            pub_hex = ""

    session_factory = getattr(request.app.state, "session_factory", None)
    total_templates = 0
    format_counts: dict[int, int] = {1: 0, 2: 0}

    if session_factory is not None:
        from freqid_server.storage.models import TemplateOrm
        async with session_factory() as session:
            stmt = select(TemplateOrm.format_version, func.count(TemplateOrm.id)).group_by(TemplateOrm.format_version)
            res = await session.execute(stmt)
            for f_ver, cnt in res.all():
                format_counts[f_ver] = cnt
                total_templates += cnt

    anomaly_det = getattr(request.app.state, "anomaly_detector", None)
    anomaly_stats = {
        "threshold": cfg.decision_threshold,
        "delta": 0.05,
        "near_threshold_events": anomaly_det.stats.total_near_threshold_events if anomaly_det else 0,
        "anomalies_flagged": anomaly_det.stats.total_anomalies_flagged if anomaly_det else 0,
    }

    return SecurityStatusResponse(
        tls_min_version="TLSv1.2",
        active_master_key_id=active_key_id,
        key_hierarchy_configured=key_provider is not None,
        template_protection={
            "algorithm": "Keyed-Orthogonal-O512 + AES-256-GCM",
            "total_templates": total_templates,
            "format_v1_legacy": format_counts.get(1, 0),
            "format_v2_rotated": format_counts.get(2, 0),
            "all_migrated": (format_counts.get(1, 0) == 0),
        },
        payload_sealing={
            "status": "active",
            "format": "PF02",
            "algorithm": "X25519-HKDF-AES256GCM",
            "public_key_hex": pub_hex,
        },
        anomaly_detector=anomaly_stats,
    )

