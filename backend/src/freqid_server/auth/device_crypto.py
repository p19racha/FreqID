# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
device_crypto.py: Ed25519 cryptographic primitives for edge device signature verification.
Uses standard cryptography library to sign and verify canonical HTTP request strings.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519


def compute_body_digest(body: bytes) -> str:
    """Computes hexadecimal SHA-256 digest of request body."""
    return hashlib.sha256(body).hexdigest()


def build_canonical_request_string(
    method: str,
    path: str,
    timestamp: str | int,
    nonce: str,
    body_digest: str,
) -> bytes:
    """
    Constructs the canonical byte string to be signed/verified:
    METHOD\nPATH\nTIMESTAMP\nNONCE\nBODY_DIGEST
    """
    canonical = f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_digest}"
    return canonical.encode("utf-8")


def generate_device_keypair() -> tuple[str, str]:
    """
    Generates a new Ed25519 keypair for edge device.
    Returns (private_key_base64, public_key_base64).
    """
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    priv_bytes = private_key.private_bytes_raw()
    pub_bytes = public_key.public_bytes_raw()

    return (
        base64.b64encode(priv_bytes).decode("ascii"),
        base64.b64encode(pub_bytes).decode("ascii"),
    )


def sign_request(
    private_key_b64: str,
    method: str,
    path: str,
    timestamp: str | int,
    nonce: str,
    body: bytes,
) -> str:
    """Signs request components using Ed25519 private key, returning Base64 signature."""
    priv_bytes = base64.b64decode(private_key_b64)
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)

    body_digest = compute_body_digest(body)
    canonical = build_canonical_request_string(method, path, timestamp, nonce, body_digest)

    sig = private_key.sign(canonical)
    return base64.b64encode(sig).decode("ascii")


def verify_request_signature(
    public_key_b64: str,
    signature_b64: str,
    method: str,
    path: str,
    timestamp: str | int,
    nonce: str,
    body: bytes,
) -> bool:
    """
    Verifies an Ed25519 signature over canonical request components.
    Returns True if valid, False otherwise.
    """
    try:
        pub_bytes = base64.b64decode(public_key_b64)
        sig_bytes = base64.b64decode(signature_b64)

        if len(pub_bytes) != 32 or len(sig_bytes) != 64:
            return False

        public_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
        body_digest = compute_body_digest(body)
        canonical = build_canonical_request_string(method, path, timestamp, nonce, body_digest)

        public_key.verify(sig_bytes, canonical)
        return True
    except InvalidSignature:
        return False
    except Exception:
        return False
