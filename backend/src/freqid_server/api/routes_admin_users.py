# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
routes_admin_users.py: Admin user lifecycle endpoints delegating to Phase 5 services.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from freqid_server.api.routes_admin_auth import get_current_admin
from freqid_server.api.schemas import UserExportResponse, UserStatusResponse
from freqid_server.auth.base import AuthenticatedPrincipal
from freqid_server.auth.permissions import (
    PERM_USER_DELETE,
    PERM_USER_DISABLE,
    PERM_USER_ENABLE,
    PERM_USER_EXPORT,
    PERM_USER_LIST,
    PERM_USER_READ,
)
from freqid_server.errors import (
    InsufficientScopeError,
    UserNotFoundError,
    ValidationError,
)
from freqid_server.storage.models import TemplateOrm, UserOrm

router = APIRouter(prefix="/v1/admin/users", tags=["Admin Users"])


def require_admin_permission(perm: str):
    async def _checker(admin: AuthenticatedPrincipal = Depends(get_current_admin)) -> AuthenticatedPrincipal:
        if not admin.has_scope(perm):
            raise InsufficientScopeError(f"Admin lacks required permission: '{perm}'.")
        return admin
    return _checker


@router.get("", response_model=list[dict[str, Any]], operation_id="admin_list_users")
async def list_users(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_USER_LIST)),
) -> list[dict[str, Any]]:
    """Lists enrolled user identities and operational statuses."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if not session_factory:
        store = request.app.state.store
        if hasattr(store, "list_templates"):
            identities = await store.list_templates()
            return [{"id": str(i), "external_id": str(i), "status": "active"} for i in identities]
        return []

    async with session_factory() as session:
        stmt = select(UserOrm).order_by(desc(UserOrm.created_at)).limit(limit)
        res = await session.execute(stmt)
        users = res.scalars().all()
        return [
            {
                "id": str(u.id),
                "external_id": u.external_id,
                "status": u.status,
                "created_at": u.created_at.isoformat(),
                "updated_at": u.updated_at.isoformat(),
            }
            for u in users
        ]


@router.get("/{user_id}", response_model=dict[str, Any], operation_id="admin_get_user")
async def get_user(
    user_id: str,
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_USER_READ)),
) -> dict[str, Any]:
    """Retrieves identity details and template metadata for a specific user."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if not session_factory:
        store = request.app.state.store
        template = await store.get_template(user_id)
        if not template:
            raise UserNotFoundError(f"User '{user_id}' not found.")
        return {
            "id": user_id,
            "external_id": user_id,
            "status": "active",
            "model_version": template.model_version,
            "created_at": template.created_at,
        }

    async with session_factory() as session:
        # Check by external_id or UUID
        stmt = select(UserOrm).where((UserOrm.external_id == user_id))
        res = await session.execute(stmt)
        user = res.scalars().first()

        if not user:
            try:
                u_uuid = uuid.UUID(user_id)
                stmt2 = select(UserOrm).where(UserOrm.id == u_uuid)
                res2 = await session.execute(stmt2)
                user = res2.scalars().first()
            except ValueError:
                pass

        if not user:
            raise UserNotFoundError(f"User '{user_id}' not found.")

        tmpl_stmt = select(TemplateOrm).where(TemplateOrm.user_id == user.id)
        tmpl_res = await session.execute(tmpl_stmt)
        tmpl = tmpl_res.scalars().first()

        return {
            "id": str(user.id),
            "external_id": user.external_id,
            "status": user.status,
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat(),
            "template": {
                "template_id": tmpl.template_id,
                "model_version": tmpl.model_version,
                "frames_used": tmpl.frames_used,
                "version": tmpl.version,
            }
            if tmpl
            else None,
        }


@router.post("/{user_id}/disable", response_model=UserStatusResponse, operation_id="admin_disable_user")
async def disable_user(
    user_id: str,
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_USER_DISABLE)),
) -> UserStatusResponse:
    """Deactivates a user identity, suppressing verification without deleting biometric data."""
    store = request.app.state.store
    await store.disable_user(user_id)
    return UserStatusResponse(status="disabled", user_id=user_id, message="Identity disabled.")


@router.post("/{user_id}/enable", response_model=UserStatusResponse, operation_id="admin_enable_user")
async def enable_user(
    user_id: str,
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_USER_ENABLE)),
) -> UserStatusResponse:
    """Reactivates a disabled user identity."""
    store = request.app.state.store
    await store.enable_user(user_id)
    return UserStatusResponse(status="active", user_id=user_id, message="Identity enabled.")


@router.get("/{user_id}/export", response_model=UserExportResponse, operation_id="admin_export_user")
async def export_user(
    user_id: str,
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_USER_EXPORT)),
) -> UserExportResponse:
    """GDPR Article 15 export delivering metadata and chronological audit activity."""
    store = request.app.state.store
    audit_history = await store.get_user_audit_history(user_id, limit=50)
    template = await store.get_template(user_id)

    if not template:
        raise UserNotFoundError(f"User '{user_id}' not found.")

    return UserExportResponse(
        user_id=user_id,
        status="active",
        created_at=template.created_at,
        updated_at=template.updated_at,
        template_metadata={
            "model_version": template.model_version,
            "sample_count": template.sample_count,
            "quality_score": template.quality_score,
            "version": template.optimistic_version,
        },
        audit_events=audit_history,
    )


@router.delete("/{user_id}", response_model=dict[str, str], operation_id="admin_delete_user")
async def delete_user(
    user_id: str,
    request: Request,
    admin: AuthenticatedPrincipal = Depends(require_admin_permission(PERM_USER_DELETE)),
) -> dict[str, str]:
    """GDPR Article 17 erasure: purges identity and encrypted biometric templates completely."""
    store = request.app.state.store
    await store.delete_user_completely(user_id)
    return {"status": "deleted", "user_id": user_id}
