# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
passwords.py: Cryptographically secure password hashing and verification using Argon2id.
Enforces RFC 9106 standards, minimum length policy, common-password rejection,
and constant-time verification with calibrated dummy hashing against enumeration timing attacks.
"""

from __future__ import annotations

import secrets
from typing import Final

import argon2
from argon2.exceptions import VerifyMismatchError

from freqid_server.errors import ValidationError

# RFC 9106 recommended parameters:
# Memory: 64 MiB (65536 KiB), Time: 3 iterations, Parallelism: 4 threads, Hash length: 32 bytes
PASSWORD_HASHER: Final = argon2.PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    type=argon2.Type.ID,
)

# Baseline dummy hash computed once at process startup for timing equalization on unknown usernames
DUMMY_BASELINE_HASH: Final = PASSWORD_HASHER.hash("dummy_calibration_password_baseline_string")

# Bundled list of common weak passwords
COMMON_PASSWORDS: Final[frozenset[str]] = frozenset(
    {
        "password",
        "123456789012",
        "adminpassword",
        "administrator",
        "changeme1234",
        "correcthorsebatterystaple",
        "freqidpassword",
        "iloveyou1234",
        "letmein12345",
        "masterpassword",
        "monkey123456",
        "password1234",
        "qwerty123456",
        "rootpassword1",
        "secretpassword",
        "trustnoone12",
        "welcome12345",
    }
)

MINIMUM_PASSWORD_LENGTH: Final[int] = 12


def validate_password_policy(password: str) -> None:
    """
    Validates password against complexity and security policies:
    1. Minimum 12 characters.
    2. Not in common weak passwords blocklist.
    """
    if not password or len(password) < MINIMUM_PASSWORD_LENGTH:
        raise ValidationError(
            f"Password must be at least {MINIMUM_PASSWORD_LENGTH} characters long."
        )

    if password.lower() in COMMON_PASSWORDS:
        raise ValidationError("Password is too common and easily guessable.")


def hash_password(password: str) -> str:
    """Hashes password using Argon2id."""
    validate_password_policy(password)
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """
    Verifies a password against an Argon2id hash using constant-time comparison.
    Returns True if valid, False otherwise.
    """
    try:
        return bool(PASSWORD_HASHER.verify(hashed, password))
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def verify_dummy_baseline(password: str) -> bool:
    """
    Executes a calibrated dummy Argon2id hash verification to ensure
    execution timing for unknown usernames matches that of existing users.
    Always returns False.
    """
    try:
        PASSWORD_HASHER.verify(DUMMY_BASELINE_HASH, password)
    except Exception:
        pass
    return False
