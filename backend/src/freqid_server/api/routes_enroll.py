# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
routes_enroll.py: Multi-sample enrollment and identity lifecycle endpoint handlers.
"""

from __future__ import annotations

from typing import Any

import freqid_core as fq
from fastapi import APIRouter, Header, Request, status
from sqlalchemy import select

from freqid_server.api.schemas import (
    DeleteResponse,
    EnrollResponse,
    UserExportResponse,
    UserStatusResponse,
)
from freqid_server.audit.base import AuditEvent, coarse_score_bucket
from freqid_server.auth.base import AuthenticatedPrincipal
from freqid_server.crypto.payload_envelope import unseal_request_payload
from freqid_server.errors import (
    AuthenticationError,
    InvalidPayloadError,
    UserNotFoundError,
)
from freqid_server.services.enrollment import EnrollmentService
from freqid_server.storage.models import AuditEventOrm, UserOrm
from freqid_server.storage.postgres import PostgreSQLTemplateStore

router = APIRouter(tags=["Enrollment and Lifecycle"])


def get_dependencies(request: Request) -> tuple:
    app_state = request.app.state
    return (
        app_state.config,
        app_state.auth,
        app_state.enrollment,
        app_state.store,
        app_state.gallery,
        getattr(app_state, "audit_sink", None),
    )


@router.post(
    "/v1/enroll",
    response_model=EnrollResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Multi-sample Biometric Enrollment",
    operation_id="enroll_frames",
)
@router.post(
    "/api/v1/enroll/frames",
    response_model=EnrollResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def enroll_endpoint(
    request: Request,
    x_device_id: str | None = Header(None, alias="X-Device-ID"),
    x_user_id: str | None = Header(None, alias="X-User-ID"),
    x_re_enroll: bool | None = Header(False, alias="X-Re-Enroll"),
) -> EnrollResponse:
    config, auth, enrollment_service, _, _, audit_sink = get_dependencies(request)
    req_id = getattr(request.state, "request_id", "unknown")

    if not x_device_id:
        raise AuthenticationError("Missing required header: X-Device-ID")
    if not x_user_id:
        raise InvalidPayloadError("Missing required header: X-User-ID")

    # 1. Authenticate caller and enforce 'enroll' scope
    principal: AuthenticatedPrincipal = await auth.authenticate(request, required_scope="enroll")

    # 2. Parse binary body: supports framed multi-payload stream or single payload (sealed or unsealed)
    body = await request.body()
    if not body:
        raise InvalidPayloadError("Enrollment request body cannot be empty.")

    try:
        unsealed_body = unseal_request_payload(
            request=request,
            body=body,
            expected_device_id=x_device_id,
            expected_request_id=req_id,
        )
    except Exception as e:
        raise InvalidPayloadError(f"Sealed payload envelope rejected: {e}") from e

    payloads: list[fq.PartialFacePayload] = []
    try:
        payloads = EnrollmentService.unpack_framed_payloads(
            packed_bytes=unsealed_body,
            max_frames=config.enroll_max_frames,
        )
    except InvalidPayloadError:
        # Fallback to single payload if framing header was not used
        try:
            single = fq.PartialFacePayload.from_bytes(unsealed_body)
            payloads = [single]
        except Exception as e:
            raise InvalidPayloadError(f"Corrupted or invalid enrollment payload stream: {e}") from e

    # 3. Coordinate multi-sample enrollment, outlier rejection, and template synthesis
    metadata = {
        "device_id": x_device_id,
        "principal_id": principal.principal_id,
        "principal_type": principal.principal_type,
        "request_id": req_id,
    }
    result = await enrollment_service.enroll_user(
        user_id=x_user_id,
        payloads=payloads,
        metadata=metadata,
        is_re_enroll=bool(x_re_enroll),
    )

    # 4. Asynchronously emit audit event
    if audit_sink is not None:
        await audit_sink.emit(
            AuditEvent(
                event_type="re_enroll" if x_re_enroll else "enroll",
                principal_type=principal.principal_type or ("device" if x_device_id else "admin"),
                principal_id=principal.principal_id,
                device_id=x_device_id,
                user_external_id=result["user_id"],
                decision="match",
                score_bucket=coarse_score_bucket(result.get("quality_score")),
                request_id=req_id,
                model_version=config.model_version,
                client_ip=getattr(request.client, "host", None),
            )
        )

    return EnrollResponse(
        status="enrolled",
        user_id=result["user_id"],
        template_id=result["template_id"],
        frames_processed=result["frames_processed"],
        frames_accepted=result["frames_accepted"],
        outliers_rejected=result["outliers_rejected"],
        quality_score=result["quality_score"],
        duplicate_warning=result.get("duplicate_warning"),
    )


@router.post(
    "/v1/users/{user_id}/disable",
    response_model=UserStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Disable User",
    operation_id="disable_user",
)
async def disable_user_endpoint(
    user_id: str,
    request: Request,
) -> UserStatusResponse:
    config, auth, enrollment_service, _, _, audit_sink = get_dependencies(request)
    principal = await auth.authenticate(request, required_scope="admin")
    await enrollment_service.disable_user(user_id)

    if audit_sink is not None:
        await audit_sink.emit(
            AuditEvent(
                event_type="disable",
                principal_type="admin",
                principal_id=principal.principal_id,
                user_external_id=user_id,
                decision="match",
                request_id=getattr(request.state, "request_id", "unknown"),
                model_version=config.model_version,
                client_ip=getattr(request.client, "host", None),
            )
        )

    return UserStatusResponse(
        status="disabled",
        user_id=user_id,
        message=f"User '{user_id}' has been disabled and evicted from active matching.",
    )


@router.post(
    "/v1/users/{user_id}/enable",
    response_model=UserStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Enable User",
    operation_id="enable_user",
)
async def enable_user_endpoint(
    user_id: str,
    request: Request,
) -> UserStatusResponse:
    config, auth, enrollment_service, _, _, audit_sink = get_dependencies(request)
    principal = await auth.authenticate(request, required_scope="admin")
    await enrollment_service.enable_user(user_id)

    if audit_sink is not None:
        await audit_sink.emit(
            AuditEvent(
                event_type="enable",
                principal_type="admin",
                principal_id=principal.principal_id,
                user_external_id=user_id,
                decision="match",
                request_id=getattr(request.state, "request_id", "unknown"),
                model_version=config.model_version,
                client_ip=getattr(request.client, "host", None),
            )
        )

    return UserStatusResponse(
        status="active",
        user_id=user_id,
        message=f"User '{user_id}' has been enabled and restored to active matching.",
    )


@router.get(
    "/v1/users/{user_id}/export",
    response_model=UserExportResponse,
    status_code=status.HTTP_200_OK,
    summary="Export User Stored Data (Metadata Only)",
    operation_id="export_user",
)
async def export_user_endpoint(
    user_id: str,
    request: Request,
) -> UserExportResponse:
    _, auth, _, store, _, _ = get_dependencies(request)
    await auth.authenticate(request, required_scope="admin")

    template = await store.get_template(user_id)
    if not template:
        raise UserNotFoundError(f"User '{user_id}' not found.")

    audit_records: list[dict[str, Any]] = []
    if isinstance(store, PostgreSQLTemplateStore):
        async with store.session_factory() as session:
            stmt_u = select(UserOrm).where(UserOrm.external_id == user_id)
            res_u = await session.execute(stmt_u)
            user_orm = res_u.scalar_one_or_none()
            if user_orm:
                stmt_ev = (
                    select(AuditEventOrm)
                    .where(AuditEventOrm.user_id == user_orm.id)
                    .order_by(AuditEventOrm.event_time.desc())
                    .limit(100)
                )
                res_ev = await session.execute(stmt_ev)
                for ev in res_ev.scalars():
                    audit_records.append({
                        "event_id": str(ev.id),
                        "event_type": ev.event_type,
                        "event_time": ev.event_time.isoformat(),
                        "decision": ev.decision,
                        "score_bucket": ev.score_bucket,
                        "request_id": ev.request_id,
                    })

    return UserExportResponse(
        user_id=user_id,
        status="active",
        created_at=template.enrolled_at_iso,
        updated_at=template.enrolled_at_iso,
        template_metadata={
            "template_id": template.template_id,
            "model_version": template.model_version,
            "frames_used": template.frames_used,
            "metadata": template.metadata,
        },
        audit_events=audit_records,
    )


@router.delete(
    "/v1/users/{user_id}",
    response_model=DeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete User Template (Right-to-be-Forgotten)",
    operation_id="delete_user",
)
@router.delete(
    "/api/v1/users/{user_id}",
    response_model=DeleteResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def delete_user_endpoint(
    user_id: str,
    request: Request,
) -> DeleteResponse:
    config, auth, _, store, gallery, audit_sink = get_dependencies(request)

    # 1. Authenticate caller and enforce 'admin' scope
    principal = await auth.authenticate(request, required_scope="admin")

    # 2. Right-to-be-forgotten complete deletion across all tables
    deleted = await store.delete_user_completely(user_id)
    if not deleted:
        raise UserNotFoundError(f"User identity '{user_id}' was not found.")

    # 3. Remove template from in-memory gallery
    await gallery.remove(user_id)

    # 4. Asynchronously emit audit event
    if audit_sink is not None:
        await audit_sink.emit(
            AuditEvent(
                event_type="delete",
                principal_type="admin",
                principal_id=principal.principal_id,
                user_external_id=user_id,
                decision="match",
                request_id=getattr(request.state, "request_id", "unknown"),
                model_version=config.model_version,
                client_ip=getattr(request.client, "host", None),
            )
        )

    return DeleteResponse(
        status="deleted",
        user_id=user_id,
        message=f"Biometric template for user '{user_id}' has been permanently deleted and audit references anonymized.",
    )
