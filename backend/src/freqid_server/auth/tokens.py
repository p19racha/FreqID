# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
tokens.py: JWT Access Token and Rotating Refresh Token issuance and verification.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

from freqid_server.auth.permissions import get_permissions_for_role
from freqid_server.errors import AuthenticationError

JWT_ALGORITHM = "HS256"


def create_access_token(
    admin_id: uuid.UUID | str,
    username: str,
    role: str,
    secret_key: str,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Creates a signed JWT access token containing subject ID, username, role, and granted permissions.
    """
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=15))

    permissions = list(get_permissions_for_role(role))

    payload = {
        "sub": str(admin_id),
        "username": username,
        "role": role,
        "permissions": permissions,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": str(uuid.uuid4()),
    }

    return jwt.encode(payload, secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, secret_key: str) -> dict[str, Any]:
    """
    Decodes and validates a signed JWT access token.
    Raises AuthenticationError if expired or invalid.
    """
    try:
        payload = jwt.decode(token, secret_key, algorithms=[JWT_ALGORITHM])
        return payload
    except ExpiredSignatureError as e:
        raise AuthenticationError("Access token has expired.") from e
    except InvalidTokenError as e:
        raise AuthenticationError("Invalid access token.") from e


def generate_refresh_token() -> str:
    """Generates a cryptographically secure random refresh token string (256 bits)."""
    return secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    """Computes SHA-256 hash of raw token for safe storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
