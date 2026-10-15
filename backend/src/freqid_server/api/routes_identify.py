# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
routes_identify.py: 1:N biometric identification endpoint handlers.
"""

from __future__ import annotations

import freqid_core as fq
from fastapi import APIRouter, Header, Request, status

from freqid_server.api.schemas import CandidateMatch, IdentifyResponse
from freqid_server.audit.base import AuditEvent, coarse_score_bucket
from freqid_server.auth.base import AuthenticatedPrincipal
from freqid_server.crypto.payload_envelope import unseal_request_payload
from freqid_server.errors import (
    AuthenticationError,
    InvalidPayloadError,
)

router = APIRouter(tags=["Biometric Identification"])


def get_dependencies(request: Request) -> tuple:
    app_state = request.app.state
    return (
        app_state.config,
        app_state.auth,
        app_state.inference,
        app_state.matching,
        app_state.gallery,
        getattr(app_state, "audit_sink", None),
    )


@router.post(
    "/v1/identify",
    response_model=IdentifyResponse,
    status_code=status.HTTP_200_OK,
    summary="1:N Biometric Identification",
    operation_id="biometric_identify",
)
@router.post(
    "/api/v1/auth/identify",
    response_model=IdentifyResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def identify_endpoint(
    request: Request,
    x_device_id: str | None = Header(None, alias="X-Device-ID"),
    x_nonce: str | None = Header(None, alias="X-Nonce"),
    x_top_k: int | None = Header(5, alias="X-Top-K"),
) -> IdentifyResponse:
    config, auth, inference, matching, gallery, audit_sink = get_dependencies(request)
    req_id = getattr(request.state, "request_id", "unknown")

    if not x_device_id:
        raise AuthenticationError("Missing required header: X-Device-ID")
    if not x_nonce:
        raise AuthenticationError("Missing required header: X-Nonce")

    # 1. Authenticate caller and enforce 'identify' scope
    principal: AuthenticatedPrincipal = await auth.authenticate(request, required_scope="identify")

    # 2. Parse PartialFacePayload binary body (supports PF02 sealed envelope or raw payload)
    body = await request.body()
    try:
        unsealed_body = unseal_request_payload(
            request=request,
            body=body,
            expected_device_id=x_device_id,
            expected_request_id=req_id,
        )
    except Exception as e:
        raise InvalidPayloadError(f"Sealed payload envelope rejected: {e}") from e

    try:
        payload = fq.PartialFacePayload.from_bytes(unsealed_body)
    except Exception as e:
        raise InvalidPayloadError(f"Corrupted or invalid PartialFacePayload: {e}") from e

    # 3. Neural forward inference
    query_emb = await inference.embed(payload)

    # 4. Search in-memory vector gallery
    top_k_clamped = min(max(1, int(x_top_k or 5)), 50)
    match_results = gallery.search(
        query_embedding=query_emb,
        top_k=top_k_clamped,
        threshold=config.decision_threshold,
        score_floor=0.20,
    )

    # 5. Format candidate output with optional score masking
    mask_scores = config.mask_scores_in_production and not principal.has_scope("admin")
    top_cand_dict, cand_dicts = matching.format_candidates(match_results, mask_scores=mask_scores)

    top_candidate = CandidateMatch(**top_cand_dict) if top_cand_dict else None
    candidates = [CandidateMatch(**c) for c in cand_dicts]

    # 6. Asynchronously emit audit event
    if audit_sink is not None:
        target_user = top_candidate.user_id if top_candidate else None
        top_score = match_results[0].similarity if match_results else None
        await audit_sink.emit(
            AuditEvent(
                event_type="identify",
                principal_type=principal.principal_type or "device",
                principal_id=principal.principal_id,
                device_id=x_device_id,
                user_external_id=target_user,
                decision="match" if top_candidate is not None else "no_match",
                score_bucket=coarse_score_bucket(top_score),
                request_id=req_id,
                model_version=config.model_version,
                client_ip=getattr(request.client, "host", None),
            )
        )

    return IdentifyResponse(
        status="success",
        request_id=req_id,
        is_match=top_candidate is not None,
        top_candidate=top_candidate,
        candidates=candidates,
    )
