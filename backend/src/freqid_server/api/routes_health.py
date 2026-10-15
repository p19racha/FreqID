# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
routes_health.py: Health check, readiness probe, and model metadata endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from sqlalchemy import func, select

from freqid_server.api.schemas import (
    HealthResponse,
    ModelInfoResponse,
    ModelMigrationReportResponse,
    ReadyResponse,
)
from freqid_server.storage.models import TemplateOrm
from freqid_server.storage.postgres import PostgreSQLTemplateStore

router = APIRouter(tags=["Health and System"])


def get_dependencies(request: Request) -> tuple:
    app_state = request.app.state
    return (
        app_state.config,
        app_state.inference,
        app_state.gallery,
        app_state.store,
    )


@router.get(
    "/healthz",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness Probe",
    operation_id="healthz",
)
@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def healthz_endpoint() -> HealthResponse:
    """Returns 200 OK if the HTTP process is running."""
    return HealthResponse(status="ok", service="freqid-server")


@router.get(
    "/readyz",
    response_model=ReadyResponse,
    status_code=status.HTTP_200_OK,
    summary="Readiness Probe",
    operation_id="readyz",
)
async def readyz_endpoint(request: Request) -> ReadyResponse:
    """Returns readiness status including embedder availability and gallery cache count."""
    config, inference, gallery, store = get_dependencies(request)
    is_ready = inference.is_ready
    store_connected = await store.ping()

    return ReadyResponse(
        status="ready" if (is_ready and store_connected) else "not_ready",
        model_loaded=is_ready,
        model_version=config.model_version,
        backend=inference.backend if is_ready else "unknown",
        device=inference.device if is_ready else "unknown",
        store_connected=store_connected,
        enrolled_identities=gallery.count,
    )


@router.get(
    "/v1/model",
    response_model=ModelInfoResponse,
    status_code=status.HTTP_200_OK,
    summary="Model Metadata",
    operation_id="get_model_info",
)
async def model_info_endpoint(request: Request) -> ModelInfoResponse:
    """Returns non-sensitive metadata for active server-side neural model."""
    config, inference, _, _ = get_dependencies(request)
    info = inference.model_info

    return ModelInfoResponse(
        model_version=config.model_version,
        backend=inference.backend,
        device=inference.device,
        embedding_dim=info.embedding_dim,
        input_channels=info.input_shape[0],
        checkpoint_sha256=inference.checkpoint_sha256,
    )


@router.get(
    "/v1/model/migration-report",
    response_model=ModelMigrationReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Model Version Migration Report",
    operation_id="get_model_migration_report",
)
async def model_migration_report_endpoint(request: Request) -> ModelMigrationReportResponse:
    """Reports compatibility and re-enrollment requirements across model versions."""
    config, _, gallery, store = get_dependencies(request)
    active_version = config.model_version

    breakdown: dict[str, int] = {}
    total = 0
    compatible = 0

    if isinstance(store, PostgreSQLTemplateStore):
        async with store.session_factory() as session:
            stmt = select(TemplateOrm.model_version, func.count(TemplateOrm.id)).group_by(
                TemplateOrm.model_version
            )
            res = await session.execute(stmt)
            breakdown = dict(res.all())
            total = sum(breakdown.values())
            compatible = breakdown.get(active_version, 0)
    else:
        # In-memory store
        total = await store.count()
        compatible = gallery.count
        breakdown = {active_version: compatible}

    needs_re_enroll = total - compatible

    return ModelMigrationReportResponse(
        active_model_version=active_version,
        total_templates=total,
        compatible_templates=compatible,
        needs_reenrollment_count=needs_re_enroll,
        outdated_model_breakdown=breakdown,
    )
