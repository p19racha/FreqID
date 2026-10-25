# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
authenticator.py: Unified request authenticator supporting Ed25519 device signatures,
admin JWT bearer tokens, and development static tokens with immediate revocation enforcement.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from freqid_server.audit.base import hash_client_ip
from freqid_server.auth.base import AuthenticatedPrincipal, RequestAuthenticator
from freqid_server.auth.device_crypto import verify_request_signature
from freqid_server.auth.lockout import LockoutManager
from freqid_server.auth.tokens import decode_access_token
from freqid_server.config import ServerConfig
from freqid_server.errors import (
    AccountDisabledError,
    AuthenticationError,
    DeviceRevokedError,
    DeviceSuspendedError,
    InsufficientScopeError,
    ReplayDetectedError,
)
from freqid_server.storage.models import AdminUserOrm, DeviceOrm


class UnifiedAuthenticator(RequestAuthenticator):
    """
    Unified authenticator for all FreqID API endpoints:
    1. Edge Device Authentication: Ed25519 per-request signatures with timestamp and nonce verification.
    2. Admin Authentication: JWT access tokens with active account validation.
    3. Dev Static Tokens: Strictly guarded against production execution.
    """

    def __init__(
        self,
        config: ServerConfig,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        lockout_manager: LockoutManager | None = None,
    ) -> None:
        self.config = config
        self.session_factory = session_factory
        self.lockout_manager = lockout_manager or LockoutManager()
        self._nonce_cache: dict[str, float] = {}
        self._device_last_seen_cache: dict[uuid.UUID, float] = {}
        self._dev_tokens: dict[str, set[str]] = {
            t: set(s) for t, s in self.config.static_tokens.items()
        }
        # In-memory test store fallback
        self._mem_devices: dict[uuid.UUID, dict[str, Any]] = {}
        self._mem_admins: dict[uuid.UUID, dict[str, Any]] = {}

    def register_mem_device(
        self,
        device_id: uuid.UUID,
        public_key: str,
        state: str = "active",
        scopes: list[str] | None = None,
    ) -> None:
        """Helper for memory test doubles."""
        self._mem_devices[device_id] = {
            "public_key": public_key,
            "state": state,
            "scopes": scopes or ["verify"],
        }

    def register_mem_admin(
        self,
        admin_id: uuid.UUID,
        username: str,
        role: str,
        is_active: bool = True,
    ) -> None:
        """Helper for memory test doubles."""
        self._mem_admins[admin_id] = {
            "username": username,
            "role": role,
            "is_active": is_active,
        }

    def _check_nonce(self, nonce: str, now: float) -> None:
        """Enforces sliding-window nonce deduplication against replay attacks."""
        ttl = self.config.nonce_ttl_seconds
        # Evict expired nonces
        expired_keys = [k for k, exp in self._nonce_cache.items() if exp < now]
        for k in expired_keys:
            del self._nonce_cache[k]

        if nonce in self._nonce_cache:
            raise ReplayDetectedError(f"Request nonce '{nonce}' has already been consumed.")

        self._nonce_cache[nonce] = now + ttl

    async def authenticate(
        self, request: Request, required_scope: str | None = None
    ) -> AuthenticatedPrincipal:
        headers = request.headers
        auth_header = headers.get("Authorization")
        device_id_hdr = headers.get("X-Device-ID")
        sig_hdr = headers.get("X-Signature")

        # 1. Device Signature Authentication
        if device_id_hdr and sig_hdr:
            return await self._authenticate_device(request, required_scope)

        # 2. Bearer Token Authentication (Admin JWT or Dev Static Token)
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            # Try Admin JWT
            try:
                jwt_payload = decode_access_token(token, self.config.master_key)
                return await self._authenticate_admin_jwt(jwt_payload, required_scope)
            except AuthenticationError:
                # If not a valid JWT, check if it's a dev static token
                pass

            # Try Dev Static Token
            if token in self._dev_tokens:
                return self._authenticate_static_token(
                    token, headers.get("X-Device-ID"), required_scope
                )

        raise AuthenticationError("Missing or invalid authentication credentials.")

    async def _authenticate_device(
        self, request: Request, required_scope: str | None
    ) -> AuthenticatedPrincipal:
        headers = request.headers
        device_id_str = headers["X-Device-ID"]
        signature_b64 = headers["X-Signature"]
        timestamp_str = headers.get("X-Timestamp")
        nonce = headers.get("X-Nonce")

        if not timestamp_str or not nonce:
            raise AuthenticationError("Missing X-Timestamp or X-Nonce signature headers.")

        # Validate timestamp window
        now = time.time()
        try:
            req_time = float(timestamp_str)
        except ValueError as e:
            raise AuthenticationError("Invalid X-Timestamp header.") from e

        if abs(now - req_time) > self.config.nonce_ttl_seconds:
            raise AuthenticationError(
                f"Request timestamp {req_time} is outside the acceptable skew window."
            )

        # Nonce deduplication
        self._check_nonce(nonce, now)

        # Validate UUID format
        try:
            device_uuid = uuid.UUID(device_id_str)
        except ValueError as e:
            raise AuthenticationError(f"Invalid device UUID: {device_id_str}") from e

        # Resolve device from DB or memory
        pub_key: str
        state: str
        scopes: list[str]

        if self.session_factory:
            async with self.session_factory() as session:
                stmt = select(DeviceOrm).where(DeviceOrm.id == device_uuid)
                res = await session.execute(stmt)
                device = res.scalars().first()

                if not device:
                    raise AuthenticationError(f"Device '{device_uuid}' is not registered.")

                pub_key = device.public_key
                state = device.state
                scopes = list(device.scopes) if isinstance(device.scopes, list) else []

                # Throttle last_seen writes to once per 60 seconds
                last_written = self._device_last_seen_cache.get(device_uuid, 0.0)
                if now - last_written > 60.0:
                    self._device_last_seen_cache[device_uuid] = now
                    client_ip = request.client.host if request.client else None
                    up_stmt = (
                        update(DeviceOrm)
                        .where(DeviceOrm.id == device_uuid)
                        .values(
                            last_seen=datetime.now(timezone.utc),
                            last_ip_hash=hash_client_ip(client_ip),
                        )
                    )
                    await session.execute(up_stmt)
                    await session.commit()
        else:
            if device_uuid not in self._mem_devices:
                raise AuthenticationError(f"Device '{device_uuid}' is not registered.")
            dev_data = self._mem_devices[device_uuid]
            pub_key = dev_data["public_key"]
            state = dev_data["state"]
            scopes = list(dev_data["scopes"])

        # Enforce device state invariants
        if state == "revoked":
            raise DeviceRevokedError("Device has been permanently revoked.")
        if state == "suspended":
            raise DeviceSuspendedError("Device is currently suspended.")
        if state == "pending":
            raise AuthenticationError("Device registration is pending administrator approval.")
        if state != "active":
            raise AuthenticationError(f"Device is in non-operational state: '{state}'.")

        # Verify cryptographic signature
        body_bytes = await request.body()
        is_valid = verify_request_signature(
            public_key_b64=pub_key,
            signature_b64=signature_b64,
            method=request.method,
            path=request.url.path,
            timestamp=timestamp_str,
            nonce=nonce,
            body=body_bytes,
        )
        if not is_valid:
            raise AuthenticationError("Ed25519 cryptographic signature verification failed.")

        # Check required scope
        device_scopes = set(scopes)
        if required_scope and required_scope not in device_scopes:
            raise InsufficientScopeError(
                f"Device lacks required scope '{required_scope}' (granted: {sorted(device_scopes)})."
            )

        return AuthenticatedPrincipal(
            principal_id=str(device_uuid),
            principal_type="device",
            scopes=device_scopes,
        )

    async def _authenticate_admin_jwt(
        self, payload: dict[str, Any], required_scope: str | None
    ) -> AuthenticatedPrincipal:
        admin_id_str = payload.get("sub")
        payload.get("role", "operator")
        permissions = set(payload.get("permissions", []))

        if not admin_id_str:
            raise AuthenticationError("Invalid JWT token: missing subject.")

        try:
            admin_uuid = uuid.UUID(admin_id_str)
        except ValueError as e:
            raise AuthenticationError(f"Invalid admin UUID: {admin_id_str}") from e

        # Validate that admin account is still active
        if self.session_factory:
            async with self.session_factory() as session:
                stmt = select(AdminUserOrm).where(AdminUserOrm.id == admin_uuid)
                res = await session.execute(stmt)
                admin = res.scalars().first()

                if not admin or not admin.is_active:
                    raise AccountDisabledError("Admin account is disabled or does not exist.")
        elif admin_uuid in self._mem_admins:
            if not self._mem_admins[admin_uuid].get("is_active", True):
                raise AccountDisabledError("Admin account is disabled.")

        # Check required scope
        if required_scope and required_scope not in permissions and "admin" not in permissions:
            raise InsufficientScopeError(f"Admin lacks required permission '{required_scope}'.")

        return AuthenticatedPrincipal(
            principal_id=str(admin_uuid),
            principal_type="admin",
            scopes=permissions,
        )

    def _authenticate_static_token(
        self, token: str, device_id: str | None, required_scope: str | None
    ) -> AuthenticatedPrincipal:
        if (
            self.config.environment == "production"
            and not self.config.allow_static_tokens_in_production
        ):
            raise AuthenticationError(
                "Static token authentication is strictly prohibited in production environment."
            )

        scopes = self._dev_tokens[token]
        if required_scope and required_scope not in scopes and "admin" not in scopes:
            raise InsufficientScopeError(f"Static token lacks required scope '{required_scope}'.")

        is_admin = "admin" in scopes
        return AuthenticatedPrincipal(
            principal_id=device_id or ("dev_admin" if is_admin else "dev_device"),
            principal_type="admin" if is_admin else "device",
            scopes=scopes,
        )
