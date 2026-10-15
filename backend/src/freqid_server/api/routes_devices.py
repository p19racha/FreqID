# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
routes_devices.py: Device pairing, heartbeat telemetry, and key rotation endpoints.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from freqid_server.api.schemas import (
    DeviceHeartbeatRequest,
    DeviceHeartbeatResponse,
    DevicePairRequest,
    DevicePairResponse,
    DeviceRotateKeyRequest,
    DeviceRotateKeyResponse,
)
from freqid_server.audit.base import AuditEvent, hash_client_ip
from freqid_server.auth.base import AuthenticatedPrincipal
from freqid_server.errors import AuthenticationError, ValidationError
from freqid_server.storage.models import (
    AuditEventOrm,
    DeviceHeartbeatOrm,
    DeviceOrm,
    PairingTokenOrm,
)

router = APIRouter(tags=["Devices"])


async def get_current_device(request: Request) -> AuthenticatedPrincipal:
    """Dependency requiring authenticated device principal."""
    authenticator = request.app.state.authenticator
    principal = await authenticator.authenticate(request)
    if principal.principal_type != "device":
        raise AuthenticationError("Device credentials required.")
    return principal


@router.post("/v1/devices/pair", response_model=DevicePairResponse, status_code=201, operation_id="device_pair")
@router.post("/api/v1/devices/pair", response_model=DevicePairResponse, status_code=201, include_in_schema=False)
async def pair_device(
    payload: DevicePairRequest,
    request: Request,
) -> DevicePairResponse:
    """Claims a pairing token and registers a new edge camera device."""
    raw_token = payload.token.strip()
    pub_key_b64 = payload.public_key.strip()
    device_name = payload.name.strip()

    if not raw_token or not pub_key_b64 or not device_name:
        raise ValidationError("token, public_key, and name are required.")

    # Validate Ed25519 public key format (32 bytes Base64)
    try:
        raw_pub = base64.b64decode(pub_key_b64)
        if len(raw_pub) != 32:
            raise ValidationError("Invalid public key length: expected 32 bytes.")
    except Exception as e:
        raise ValidationError(f"Invalid public key encoding: {e}") from e

    token_h = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    key_id = hashlib.sha256(pub_key_b64.encode("utf-8")).hexdigest()[:16]
    now = datetime.now(timezone.utc)
    dev_id = uuid.uuid4()

    session_factory = getattr(request.app.state, "session_factory", None)
    cfg = request.app.state.config

    if session_factory:
        async with session_factory() as session:
            # Check unique public key
            stmt_dup = select(DeviceOrm).where(DeviceOrm.public_key == pub_key_b64)
            res_dup = await session.execute(stmt_dup)
            if res_dup.scalars().first():
                raise ValidationError("A device with this public key is already registered.")

            # Atomically claim pairing token
            stmt = select(PairingTokenOrm).where(
                PairingTokenOrm.token_hash == token_h,
                PairingTokenOrm.is_used == False,
                PairingTokenOrm.expires_at > now,
            )
            res = await session.execute(stmt)
            token_row = res.scalars().first()

            if not token_row:
                raise ValidationError("Invalid, expired, or already consumed pairing token.")

            # Burn token atomically
            token_row.is_used = True
            token_row.used_at = now
            token_row.used_by_device_id = dev_id

            scopes = token_row.scopes_allowed if isinstance(token_row.scopes_allowed, list) else ["verify"]
            initial_state = "active" if getattr(cfg, "device_auto_approve", True) else "pending"

            device_orm = DeviceOrm(
                id=dev_id,
                name=device_name or token_row.name_hint or "Unnamed Device",
                location=token_row.location_hint,
                state=initial_state,
                scopes=scopes,
                public_key=pub_key_b64,
                key_id=key_id,
                software_version=payload.software_version,
                created_at=now,
                updated_at=now,
            )
            session.add(device_orm)

            # Record audit event
            audit_sink = getattr(request.app.state, "audit_sink", None)
            if audit_sink:
                await audit_sink.emit(
                    AuditEvent(
                        event_type="device_paired",
                        principal_type="device",
                        decision="enrolled",
                        request_id=request.headers.get("X-Request-ID", str(uuid.uuid4())),
                        principal_id=str(dev_id),
                        device_id=str(dev_id),
                        client_ip=request.client.host if request.client else None,
                    )
                )

            await session.commit()

            return DevicePairResponse(
                device_id=str(dev_id),
                state=initial_state,
                key_id=key_id,
                server_time=now.isoformat(),
            )

    # In-memory test fallback
    authenticator = request.app.state.authenticator
    authenticator.register_mem_device(dev_id, pub_key_b64, state="active", scopes=["verify"])
    return DevicePairResponse(
        device_id=str(dev_id),
        state="active",
        key_id=key_id,
        server_time=now.isoformat(),
    )


@router.post("/v1/devices/heartbeat", response_model=DeviceHeartbeatResponse, operation_id="device_heartbeat")
@router.post("/api/v1/devices/heartbeat", response_model=DeviceHeartbeatResponse, include_in_schema=False)
async def device_heartbeat(
    payload: DeviceHeartbeatRequest,
    request: Request,
    device: AuthenticatedPrincipal = Depends(get_current_device),
) -> DeviceHeartbeatResponse:
    """Heartbeat endpoint recording device telemetry and returning server time/config."""
    dev_uuid = uuid.UUID(device.principal_id)
    now = datetime.now(timezone.utc)
    session_factory = getattr(request.app.state, "session_factory", None)

    if session_factory:
        async with session_factory() as session:
            # Insert heartbeat record
            hb = DeviceHeartbeatOrm(
                device_id=dev_uuid,
                timestamp=now,
                software_version=payload.software_version,
                camera_ok=payload.camera_ok,
                uptime_seconds=payload.uptime_seconds,
                queued_payloads=payload.queued_payloads,
            )
            session.add(hb)

            # Update device last_seen
            up = (
                update(DeviceOrm)
                .where(DeviceOrm.id == dev_uuid)
                .values(
                    last_seen=now,
                    software_version=payload.software_version,
                )
            )
            await session.execute(up)
            await session.commit()

    return DeviceHeartbeatResponse(
        status="ok",
        server_time=now.isoformat(),
        state="active",
        config={"min_client_version": "0.1.0"},
    )


@router.post("/v1/devices/rotate-key", response_model=DeviceRotateKeyResponse, operation_id="device_rotate_key")
@router.post("/api/v1/devices/rotate-key", response_model=DeviceRotateKeyResponse, include_in_schema=False)
async def device_rotate_key(
    payload: DeviceRotateKeyRequest,
    request: Request,
    device: AuthenticatedPrincipal = Depends(get_current_device),
) -> DeviceRotateKeyResponse:
    """Rotates device public key signed using current active credentials."""
    new_pub_b64 = payload.new_public_key.strip()
    try:
        raw_pub = base64.b64decode(new_pub_b64)
        if len(raw_pub) != 32:
            raise ValidationError("Invalid public key length: expected 32 bytes.")
    except Exception as e:
        raise ValidationError(f"Invalid public key encoding: {e}") from e

    new_key_id = hashlib.sha256(new_pub_b64.encode("utf-8")).hexdigest()[:16]
    dev_uuid = uuid.UUID(device.principal_id)
    now = datetime.now(timezone.utc)
    session_factory = getattr(request.app.state, "session_factory", None)

    if session_factory:
        async with session_factory() as session:
            up = (
                update(DeviceOrm)
                .where(DeviceOrm.id == dev_uuid)
                .values(
                    public_key=new_pub_b64,
                    key_id=new_key_id,
                    updated_at=now,
                )
            )
            await session.execute(up)
            await session.commit()

    return DeviceRotateKeyResponse(status="key_rotated", key_id=new_key_id)
