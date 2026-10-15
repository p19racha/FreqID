# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
routes_verify.py: 1:1 biometric verification endpoint handlers.
"""

from __future__ import annotations

import freqid_core as fq
from fastapi import APIRouter, Header, Request, status

from freqid_server.api.schemas import VerifyResponse
from freqid_server.audit.base import AuditEvent, coarse_score_bucket
from freqid_server.auth.base import AuthenticatedPrincipal
from freqid_server.crypto.payload_envelope import unseal_request_payload
from freqid_server.errors import (
    AuthenticationError,
    InvalidPayloadError,
    RateLimitExceededError,
)

router = APIRouter(tags=["Biometric Verification"])


def get_dependencies(request: Request) -> tuple:
    app_state = request.app.state
    return (
        app_state.config,
        app_state.auth,
        app_state.inference,
        app_state.matching,
        app_state.store,
        app_state.rate_limiter,
        getattr(app_state, "audit_sink", None),
    )


@router.post(
    "/v1/verify",
    response_model=VerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="1:1 Biometric Verification",
    operation_id="biometric_verify",
)
@router.post(
    "/api/v1/auth/verify",
    response_model=VerifyResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def verify_endpoint(
    request: Request,
    x_device_id: str | None = Header(None, alias="X-Device-ID"),
    x_claimed_identity: str | None = Header(None, alias="X-Claimed-Identity"),
    x_nonce: str | None = Header(None, alias="X-Nonce"),
) -> VerifyResponse:
    config, auth, inference, matching, store, rate_limiter, audit_sink = get_dependencies(request)
    req_id = getattr(request.state, "request_id", "unknown")

    if not x_device_id:
        raise AuthenticationError("Missing required header: X-Device-ID")
    if not x_claimed_identity:
        raise InvalidPayloadError("Missing required header: X-Claimed-Identity")
    if not x_nonce:
        raise AuthenticationError("Missing required header: X-Nonce")

    # 1. Authenticate caller and enforce 'verify' scope
    principal: AuthenticatedPrincipal = await auth.authenticate(request, required_scope="verify")

    # 2. Check user-level lockout against brute-force guessing
    is_allowed, retry_after = rate_limiter.check_user_lockout(x_claimed_identity)
    if not is_allowed:
        if audit_sink is not None:
            await audit_sink.emit(
                AuditEvent(
                    event_type="rate_limit_block",
                    principal_type=principal.principal_type or "device",
                    principal_id=principal.principal_id,
                    device_id=x_device_id,
                    user_external_id=x_claimed_identity,
                    decision="blocked",
                    request_id=req_id,
                    model_version=config.model_version,
                    client_ip=getattr(request.client, "host", None),
                )
            )
        raise RateLimitExceededError(
            f"User '{x_claimed_identity}' is temporarily locked out due to repeated failed attempts.",
            retry_after=retry_after,
        )

    # 3. Parse PartialFacePayload binary body (supports PF02 sealed envelope or raw payload)
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

    # 4. Neural forward inference
    query_emb = await inference.embed(payload)

    # 5. Fetch enrolled template
    template = await store.get_template(x_claimed_identity)

    # 6. Biometric verification with anti-enumeration protection
    mask_scores = config.mask_scores_in_production and not principal.has_scope("admin")
    is_match, similarity = matching.verify(
        query_embedding=query_emb,
        claimed_identity=x_claimed_identity,
        template=template,
        threshold=config.decision_threshold,
        mask_scores=mask_scores,
    )

    # 6b. Hill-climbing near-threshold anomaly detection
    anomaly_detector = getattr(request.app.state, "anomaly_detector", None)
    if anomaly_detector is not None and template is not None:
        raw_sim = float(fq.cosine_similarity(query_emb, template.embedding))
        is_anomaly = anomaly_detector.check_and_record(
            device_id=x_device_id,
            user_id=x_claimed_identity,
            score=raw_sim,
        )
        if is_anomaly and audit_sink is not None:
            await audit_sink.emit(
                AuditEvent(
                    event_type="security_anomaly",
                    principal_type=principal.principal_type or "device",
                    principal_id=principal.principal_id,
                    device_id=x_device_id,
                    user_external_id=x_claimed_identity,
                    decision="hill_climbing_suspected",
                    request_id=req_id,
                    model_version=config.model_version,
                    client_ip=getattr(request.client, "host", None),
                )
            )

    # 7. Record verification outcome in lockout tracker
    rate_limiter.record_verification_result(x_claimed_identity, is_match)

    # 8. Asynchronously emit audit event
    if audit_sink is not None:
        await audit_sink.emit(
            AuditEvent(
                event_type="verify",
                principal_type=principal.principal_type or "device",
                principal_id=principal.principal_id,
                device_id=x_device_id,
                user_external_id=x_claimed_identity,
                decision="match" if is_match else "no_match",
                score_bucket=coarse_score_bucket(similarity),
                request_id=req_id,
                model_version=config.model_version,
                client_ip=getattr(request.client, "host", None),
            )
        )

    return VerifyResponse(
        status="success",
        request_id=req_id,
        is_match=is_match,
        similarity=similarity,
        threshold=config.decision_threshold,
        claimed_identity=x_claimed_identity,
        verified_identity=x_claimed_identity if is_match else None,
        device_id=x_device_id,
    )
