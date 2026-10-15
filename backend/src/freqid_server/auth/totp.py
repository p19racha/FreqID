# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
totp.py: Standard RFC 6238 Time-based One-Time Password (TOTP) implementation
with Base32 secret generation, otpauth URI formatting, and recovery code hashing.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Final

TOTP_DIGITS: Final[int] = 6
TOTP_INTERVAL: Final[int] = 30


def generate_totp_secret() -> str:
    """Generates a random 160-bit Base32 TOTP secret string."""
    random_bytes = secrets.token_bytes(20)
    return base64.b32encode(random_bytes).decode("ascii").rstrip("=")


def get_totp_uri(secret: str, username: str, issuer: str = "FreqID") -> str:
    """Formats an otpauth URI suitable for QR code display in authenticator apps."""
    return f"otpauth://totp/{issuer}:{username}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_INTERVAL}"


def generate_totp_code(secret: str, timestamp: float | None = None) -> str:
    """Generates a 6-digit TOTP code for the given secret at timestamp."""
    t = int(timestamp if timestamp is not None else time.time())
    counter = t // TOTP_INTERVAL

    # Decode secret, adding padding if needed
    padding = (8 - (len(secret) % 8)) % 8
    secret_padded = secret + ("=" * padding)
    key = base64.b32decode(secret_padded.upper())

    # Pack counter as 8-byte big-endian
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()

    # Dynamic truncation
    offset = h[-1] & 0x0F
    code_int = struct.unpack(">I", h[offset : offset + 4])[0] & 0x7FFFFFFF
    code = code_int % (10**TOTP_DIGITS)
    return f"{code:0{TOTP_DIGITS}d}"


def verify_totp_code(secret: str, code: str, window: int = 1) -> bool:
    """
    Verifies a 6-digit TOTP code with time-step window tolerance (+- window intervals).
    Uses constant-time comparison.
    """
    if not code or len(code.strip()) != TOTP_DIGITS or not code.strip().isdigit():
        return False

    code = code.strip()
    now = time.time()
    for step in range(-window, window + 1):
        expected = generate_totp_code(secret, timestamp=now + (step * TOTP_INTERVAL))
        if secrets.compare_digest(code, expected):
            return True
    return False


def generate_recovery_codes(count: int = 8) -> tuple[list[str], list[str]]:
    """
    Generates single-use recovery codes.
    Returns (plaintext_codes_for_user, hashed_codes_for_db).
    """
    plain = [secrets.token_hex(5) for _ in range(count)]  # 10 hex chars
    hashed = [hashlib.sha256(c.encode("utf-8")).hexdigest() for c in plain]
    return plain, hashed
