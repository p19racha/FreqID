# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
static_token.py: Constant-time static bearer token authenticator for development and testing.
"""

from __future__ import annotations

import secrets

from fastapi import Request

from freqid_server.auth.base import AuthenticatedPrincipal, RequestAuthenticator
from freqid_server.config import ServerConfig
from freqid_server.errors import AuthenticationError, InsufficientScopeError


class StaticTokenAuthenticator(RequestAuthenticator):
    """
    Validates pre-shared bearer tokens against configured scope mapping.
    Uses secrets.compare_digest for constant-time comparison against timing side-channels.
    """

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self._tokens: dict[str, set[str]] = {
            token: set(scopes) for token, scopes in self.config.static_tokens.items()
        }

        # Production safety guardrail
        if (
            self.config.environment == "production"
            and not self.config.allow_static_tokens_in_production
        ):
            raise RuntimeError(
                "StaticTokenAuthenticator is prohibited in production environment unless "
                "FREQID_SERVER_ALLOW_STATIC_TOKENS_IN_PRODUCTION is explicitly enabled."
            )

    async def authenticate(self, request: Request, required_scope: str | None = None) -> AuthenticatedPrincipal:
        auth_header = request.headers.get("Authorization")
        device_id = request.headers.get("X-Device-ID", "unknown_device")

        if not auth_header:
            raise AuthenticationError("Missing Authorization header.")

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise AuthenticationError("Authorization header must use 'Bearer <token>' format.")

        provided_token = parts[1]

        # Constant-time comparison across all known tokens
        matched_token: str | None = None
        matched_scopes: set[str] = set()

        for valid_token, scopes in self._tokens.items():
            if secrets.compare_digest(provided_token, valid_token):
                matched_token = valid_token
                matched_scopes = scopes
                break

        if matched_token is None:
            raise AuthenticationError("Invalid authentication token.")

        principal_type = "admin" if "admin" in matched_scopes else "device"
        principal = AuthenticatedPrincipal(
            principal_id=device_id if principal_type == "device" else "admin_user",
            principal_type=principal_type,
            scopes=matched_scopes,
        )

        if required_scope and not principal.has_scope(required_scope):
            raise InsufficientScopeError(
                f"Principal lacks required scope '{required_scope}'. Available scopes: {sorted(matched_scopes)}"
            )

        return principal
