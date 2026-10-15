# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
payload_envelope.py: Application-layer sealed envelope for PartialFace payloads.

Protects partial frequency payloads end-to-end between client device and server.
Construction:
- Key exchange: X25519 ephemeral-static ECDH
- Key derivation: HKDF-SHA256 with nonce salt and domain separation info
- AEAD: AES-256-GCM authenticated encryption
- Device binding: Ed25519 signature over envelope metadata and ciphertext
- Replay protection: In-memory sliding window TTL detector and timestamp window
"""

from __future__ import annotations

import json
import os
import struct
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC_V2 = b"PF02"
MAX_TIMESTAMP_SKEW_SECONDS = 60.0
INFO_V2 = b"FreqID-Payload-v2"


class PayloadEnvelopeError(Exception):
    """Base error for payload envelope sealing and unsealing."""


class ReplayAttackError(PayloadEnvelopeError):
    """Raised when a request ID or nonce is replayed."""


class ExpiredPayloadError(PayloadEnvelopeError):
    """Raised when envelope timestamp falls outside acceptable skew window."""


class EnvelopeTamperingError(PayloadEnvelopeError):
    """Raised when signature or AEAD authentication tag verification fails."""


class DeviceBindingError(PayloadEnvelopeError):
    """Raised when payload device binding does not match authenticated principal."""


class ReplayDetector:
    """
    Sliding window in-memory TTL replay detector.
    Tracks seen request IDs within a rolling time window.
    """

    def __init__(self, window_seconds: float = 120.0, max_entries: int = 100_000) -> None:
        self.window_seconds = window_seconds
        self.max_entries = max_entries
        self._seen: dict[str, float] = {}

    def check_and_record(self, request_id: str) -> None:
        """
        Validates that request_id has not been observed recently.
        Prunes expired entries. Raises ReplayAttackError if replayed.
        """
        now = time.time()
        self._prune(now)

        if request_id in self._seen:
            raise ReplayAttackError(f"Replay detected: request_id '{request_id}' has already been processed.")

        if len(self._seen) >= self.max_entries:
            # Emergency prune of oldest 10% if full
            sorted_items = sorted(self._seen.items(), key=lambda kv: kv[1])
            cutoff_idx = len(sorted_items) // 10
            for k, _ in sorted_items[:cutoff_idx]:
                self._seen.pop(k, None)

        self._seen[request_id] = now

    def _prune(self, now: float) -> None:
        expired = [req_id for req_id, ts in self._seen.items() if now - ts > self.window_seconds]
        for req_id in expired:
            del self._seen[req_id]

    def clear(self) -> None:
        self._seen.clear()


@dataclass(frozen=True)
class SealedPayloadHeader:
    key_id: str
    ephemeral_public_key_bytes: bytes
    nonce: bytes
    aad_bytes: bytes
    aad_dict: dict[str, Any]
    signature: bytes


def is_sealed_payload(data: bytes) -> bool:
    """Returns True if the byte buffer starts with magic header PF02."""
    return len(data) >= 4 and data[:4] == MAGIC_V2


def seal_payload(
    payload_bytes: bytes,
    server_public_key_bytes: bytes,
    key_id: str,
    device_id: str,
    request_id: str,
    timestamp_iso: str | None = None,
    device_private_key: ed25519.Ed25519PrivateKey | None = None,
) -> bytes:
    """
    Seals a raw PartialFace payload buffer into a PF02 application-layer envelope.
    """
    if timestamp_iso is None:
        timestamp_iso = datetime.now(timezone.utc).isoformat()

    # 1. Ephemeral X25519 keypair
    ephemeral_priv = x25519.X25519PrivateKey.generate()
    ephemeral_pub_bytes = ephemeral_priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    # 2. Reconstruct server X25519 public key and compute ECDH shared secret
    server_pub = x25519.X25519PublicKey.from_public_bytes(server_public_key_bytes)
    shared_secret = ephemeral_priv.exchange(server_pub)

    # 3. Derive 32-byte encryption key using HKDF-SHA256
    nonce = os.urandom(12)
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=nonce,
        info=INFO_V2,
    )
    enc_key = kdf.derive(shared_secret)

    # 4. Canonical AAD dictionary and bytes
    aad_dict = {
        "device_id": device_id,
        "format": "PF02",
        "key_id": key_id,
        "request_id": request_id,
        "timestamp": timestamp_iso,
    }
    aad_bytes = json.dumps(aad_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")

    # 5. Encrypt with AES-256-GCM
    aesgcm = AESGCM(enc_key)
    ciphertext_with_tag = aesgcm.encrypt(nonce, payload_bytes, aad_bytes)

    # 6. Optional Ed25519 device signature binding
    sig_bytes = b""
    if device_private_key is not None:
        signable = (
            MAGIC_V2
            + key_id.encode("ascii")
            + ephemeral_pub_bytes
            + nonce
            + aad_bytes
            + ciphertext_with_tag
        )
        sig_bytes = device_private_key.sign(signable)

    # 7. Wire serialization
    # Format:
    # MAGIC (4B) | key_id_len (1B) | key_id (k_len B) | pk_e (32B) | nonce (12B) |
    # aad_len (2B uint16) | aad_bytes | sig_len (1B uint8) | sig_bytes | ciphertext_with_tag
    key_id_encoded = key_id.encode("ascii")
    if len(key_id_encoded) > 255:
        raise ValueError("key_id exceeds 255 bytes")
    if len(aad_bytes) > 65535:
        raise ValueError("AAD exceeds 65535 bytes")
    if len(sig_bytes) > 255:
        raise ValueError("Signature exceeds 255 bytes")

    header_prefix = struct.pack(
        ">4sB",
        MAGIC_V2,
        len(key_id_encoded),
    ) + key_id_encoded + ephemeral_pub_bytes + nonce

    header_aad = struct.pack(">H", len(aad_bytes)) + aad_bytes
    header_sig = struct.pack(">B", len(sig_bytes)) + sig_bytes

    return header_prefix + header_aad + header_sig + ciphertext_with_tag


def parse_envelope_header(envelope_bytes: bytes) -> tuple[SealedPayloadHeader, bytes]:
    """
    Parses the envelope header without decrypting.
    Returns (header, ciphertext_with_tag).
    """
    if len(envelope_bytes) < 4 + 1 + 32 + 12 + 2 + 1 + 16:
        raise PayloadEnvelopeError("Envelope buffer too short to contain valid PF02 structure.")

    if envelope_bytes[:4] != MAGIC_V2:
        raise PayloadEnvelopeError(f"Invalid magic header: expected {MAGIC_V2!r}, got {envelope_bytes[:4]!r}")

    offset = 4
    key_id_len = envelope_bytes[offset]
    offset += 1

    if len(envelope_bytes) < offset + key_id_len + 32 + 12 + 2:
        raise PayloadEnvelopeError("Truncated header in PF02 envelope.")

    key_id = envelope_bytes[offset : offset + key_id_len].decode("ascii", errors="replace")
    offset += key_id_len

    pk_e = envelope_bytes[offset : offset + 32]
    offset += 32

    nonce = envelope_bytes[offset : offset + 12]
    offset += 12

    (aad_len,) = struct.unpack(">H", envelope_bytes[offset : offset + 2])
    offset += 2

    if len(envelope_bytes) < offset + aad_len + 1:
        raise PayloadEnvelopeError("Truncated AAD in PF02 envelope.")

    aad_bytes = envelope_bytes[offset : offset + aad_len]
    offset += aad_len

    try:
        aad_dict = json.loads(aad_bytes.decode("utf-8"))
    except Exception as e:
        raise PayloadEnvelopeError(f"Malformed JSON in AAD: {e}") from e

    sig_len = envelope_bytes[offset]
    offset += 1

    if len(envelope_bytes) < offset + sig_len + 16:  # at least 16 bytes for GCM tag
        raise PayloadEnvelopeError("Truncated signature or ciphertext in PF02 envelope.")

    sig_bytes = envelope_bytes[offset : offset + sig_len]
    offset += sig_len

    ciphertext_with_tag = envelope_bytes[offset:]

    header = SealedPayloadHeader(
        key_id=key_id,
        ephemeral_public_key_bytes=pk_e,
        nonce=nonce,
        aad_bytes=aad_bytes,
        aad_dict=aad_dict,
        signature=sig_bytes,
    )
    return header, ciphertext_with_tag


def open_payload(
    envelope_bytes: bytes,
    server_private_key: x25519.X25519PrivateKey,
    expected_device_id: str | None = None,
    expected_request_id: str | None = None,
    max_age_seconds: float = MAX_TIMESTAMP_SKEW_SECONDS,
    device_public_key: ed25519.Ed25519PublicKey | None = None,
    replay_detector: ReplayDetector | None = None,
    current_time: float | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """
    Unseals and verifies a PF02 application-layer envelope.
    Returns (decrypted_payload_bytes, aad_dict).
    """
    header, ciphertext_with_tag = parse_envelope_header(envelope_bytes)
    aad_dict = header.aad_dict

    # 1. Device ID matching
    if expected_device_id is not None:
        envelope_device_id = aad_dict.get("device_id")
        if envelope_device_id != expected_device_id:
            raise DeviceBindingError(
                f"Device mismatch: envelope bound to '{envelope_device_id}', caller is '{expected_device_id}'."
            )

    # 2. Request ID matching
    envelope_request_id = aad_dict.get("request_id")
    if expected_request_id is not None and envelope_request_id and envelope_request_id != expected_request_id:
        raise DeviceBindingError(
            f"Request ID mismatch: envelope has '{envelope_request_id}', HTTP header has '{expected_request_id}'."
        )

    # 3. Timestamp skew check
    ts_str = aad_dict.get("timestamp")
    if not ts_str:
        raise ExpiredPayloadError("Envelope missing timestamp in AAD.")

    try:
        ts_dt = datetime.fromisoformat(ts_str)
        envelope_epoch = ts_dt.timestamp()
    except Exception as e:
        raise ExpiredPayloadError(f"Invalid ISO-8601 timestamp in AAD: {e}") from e

    now = time.time() if current_time is None else current_time
    skew = abs(now - envelope_epoch)
    if skew > max_age_seconds:
        raise ExpiredPayloadError(
            f"Payload timestamp expired or skewed: skew={skew:.2f}s exceeds limit {max_age_seconds}s."
        )

    # 4. Replay check
    if replay_detector is not None:
        rec_id = envelope_request_id or f"{aad_dict.get('device_id')}:{header.nonce.hex()}"
        replay_detector.check_and_record(rec_id)

    # 5. Device signature verification
    if header.signature:
        if device_public_key is None:
            raise EnvelopeTamperingError("Envelope contains device signature but no device public key provided.")
        signable = (
            MAGIC_V2
            + header.key_id.encode("ascii")
            + header.ephemeral_public_key_bytes
            + header.nonce
            + header.aad_bytes
            + ciphertext_with_tag
        )
        try:
            device_public_key.verify(header.signature, signable)
        except InvalidSignature as e:
            raise EnvelopeTamperingError("Device signature verification failed: invalid signature.") from e
    elif device_public_key is not None:
        # Caller provided a device public key expecting signed envelopes
        raise EnvelopeTamperingError("Device signature required but envelope is unsigned.")

    # 6. ECDH key agreement
    try:
        ephemeral_pub = x25519.X25519PublicKey.from_public_bytes(header.ephemeral_public_key_bytes)
        shared_secret = server_private_key.exchange(ephemeral_pub)
    except Exception as e:
        raise PayloadEnvelopeError(f"ECDH key agreement failed: {e}") from e

    # 7. HKDF-SHA256 key derivation
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=header.nonce,
        info=INFO_V2,
    )
    enc_key = kdf.derive(shared_secret)

    # 8. AES-256-GCM authenticated decryption
    aesgcm = AESGCM(enc_key)
    try:
        decrypted_payload = aesgcm.decrypt(header.nonce, ciphertext_with_tag, header.aad_bytes)
    except InvalidTag as e:
        raise EnvelopeTamperingError("Payload decryption failed: AEAD authentication tag mismatch.") from e

    return decrypted_payload, aad_dict


def unseal_request_payload(
    request: Any,
    body: bytes,
    expected_device_id: str | None = None,
    expected_request_id: str | None = None,
) -> bytes:
    """
    Unseals request body if formatted as a PF02 sealed envelope.
    If body is not sealed, returns it unmodified for transitional backwards compatibility.
    """
    if not is_sealed_payload(body):
        return body

    app_state = getattr(request, "app", None)
    state = getattr(app_state, "state", None) if app_state is not None else getattr(request, "state", None)

    key_provider = getattr(state, "key_provider", None) if state is not None else None
    if key_provider is None and state is not None:
        store = getattr(state, "store", None)
        if store is not None and hasattr(store, "encryptor"):
            key_provider = getattr(store.encryptor, "key_provider", None)

    if key_provider is None:
        raise PayloadEnvelopeError("Server key provider not available to decrypt sealed payload.")

    server_priv, _ = key_provider.get_payload_keypair()
    replay_det = getattr(state, "replay_detector", None) if state is not None else None

    decrypted_bytes, _ = open_payload(
        envelope_bytes=body,
        server_private_key=server_priv,
        expected_device_id=expected_device_id,
        expected_request_id=expected_request_id,
        replay_detector=replay_det,
    )
    return decrypted_bytes

