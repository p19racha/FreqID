# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_payload_envelope.py: Comprehensive test suite for PF02 payload sealing and opening.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

from freqid_server.crypto.payload_envelope import (
    DeviceBindingError,
    EnvelopeTamperingError,
    ExpiredPayloadError,
    PayloadEnvelopeError,
    ReplayAttackError,
    ReplayDetector,
    is_sealed_payload,
    open_payload,
    parse_envelope_header,
    seal_payload,
)


@pytest.fixture
def server_keypair():
    priv = x25519.X25519PrivateKey.generate()
    pub = priv.public_key()
    pub_bytes = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return priv, pub_bytes


@pytest.fixture
def device_keypair():
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    return priv, pub


def test_seal_and_open_roundtrip_unsigned(server_keypair):
    server_priv, server_pub_bytes = server_keypair
    raw_payload = os.urandom(22036)

    sealed = seal_payload(
        payload_bytes=raw_payload,
        server_public_key_bytes=server_pub_bytes,
        key_id="key_v1",
        device_id="dev-01",
        request_id="req-12345",
    )

    assert is_sealed_payload(sealed)
    assert len(sealed) > len(raw_payload)
    overhead = len(sealed) - len(raw_payload)
    # Total overhead with 6-char key_id, no sig: ~165 bytes
    assert overhead < 300

    unsealed, aad = open_payload(
        envelope_bytes=sealed,
        server_private_key=server_priv,
        expected_device_id="dev-01",
        expected_request_id="req-12345",
    )

    assert unsealed == raw_payload
    assert aad["device_id"] == "dev-01"
    assert aad["request_id"] == "req-12345"
    assert aad["key_id"] == "key_v1"


def test_seal_and_open_roundtrip_signed(server_keypair, device_keypair):
    server_priv, server_pub_bytes = server_keypair
    dev_priv, dev_pub = device_keypair
    raw_payload = b"test payload bytes for biometric verification"

    sealed = seal_payload(
        payload_bytes=raw_payload,
        server_public_key_bytes=server_pub_bytes,
        key_id="key_v1",
        device_id="dev-secure-02",
        request_id="req-99999",
        device_private_key=dev_priv,
    )

    header, _ = parse_envelope_header(sealed)
    assert len(header.signature) == 64

    unsealed, aad = open_payload(
        envelope_bytes=sealed,
        server_private_key=server_priv,
        expected_device_id="dev-secure-02",
        expected_request_id="req-99999",
        device_public_key=dev_pub,
    )
    assert unsealed == raw_payload


def test_replay_detector_rejects_duplicate_request_id(server_keypair):
    server_priv, server_pub_bytes = server_keypair
    replay_det = ReplayDetector(window_seconds=60.0)
    raw_payload = b"payload 1"

    sealed = seal_payload(
        payload_bytes=raw_payload,
        server_public_key_bytes=server_pub_bytes,
        key_id="key_v1",
        device_id="dev-01",
        request_id="req-replay-1",
    )

    # First unseal succeeds
    open_payload(
        envelope_bytes=sealed,
        server_private_key=server_priv,
        replay_detector=replay_det,
    )

    # Second unseal with same request_id must be rejected
    with pytest.raises(ReplayAttackError, match="Replay detected"):
        open_payload(
            envelope_bytes=sealed,
            server_private_key=server_priv,
            replay_detector=replay_det,
        )


def test_expired_timestamp_rejected(server_keypair):
    server_priv, server_pub_bytes = server_keypair
    raw_payload = b"payload expired"
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()

    sealed = seal_payload(
        payload_bytes=raw_payload,
        server_public_key_bytes=server_pub_bytes,
        key_id="key_v1",
        device_id="dev-01",
        request_id="req-old",
        timestamp_iso=old_time,
    )

    with pytest.raises(ExpiredPayloadError, match="expired or skewed"):
        open_payload(
            envelope_bytes=sealed,
            server_private_key=server_priv,
            max_age_seconds=60.0,
        )


def test_device_id_mismatch_rejected(server_keypair):
    server_priv, server_pub_bytes = server_keypair
    raw_payload = b"payload mismatch"

    sealed = seal_payload(
        payload_bytes=raw_payload,
        server_public_key_bytes=server_pub_bytes,
        key_id="key_v1",
        device_id="dev-attacker",
        request_id="req-1",
    )

    with pytest.raises(DeviceBindingError, match="Device mismatch"):
        open_payload(
            envelope_bytes=sealed,
            server_private_key=server_priv,
            expected_device_id="dev-legit",
        )


def test_tampered_ciphertext_rejected(server_keypair):
    server_priv, server_pub_bytes = server_keypair
    raw_payload = b"payload to tamper"

    sealed = seal_payload(
        payload_bytes=raw_payload,
        server_public_key_bytes=server_pub_bytes,
        key_id="key_v1",
        device_id="dev-01",
        request_id="req-1",
    )

    # Flip the very last bit in the ciphertext / tag
    tampered = bytearray(sealed)
    tampered[-1] ^= 0x01

    with pytest.raises(EnvelopeTamperingError, match="AEAD authentication tag mismatch"):
        open_payload(
            envelope_bytes=bytes(tampered),
            server_private_key=server_priv,
        )


def test_tampered_signature_rejected(server_keypair, device_keypair):
    server_priv, server_pub_bytes = server_keypair
    dev_priv, dev_pub = device_keypair
    raw_payload = b"payload signed"

    sealed = seal_payload(
        payload_bytes=raw_payload,
        server_public_key_bytes=server_pub_bytes,
        key_id="key_v1",
        device_id="dev-01",
        request_id="req-1",
        device_private_key=dev_priv,
    )

    # Tamper with the signature bytes inside the header
    tampered = bytearray(sealed)
    # Signature is located right before ciphertext
    tampered[120] ^= 0x01

    with pytest.raises(EnvelopeTamperingError):
        open_payload(
            envelope_bytes=bytes(tampered),
            server_private_key=server_priv,
            device_public_key=dev_pub,
        )


def test_wrong_server_private_key_fails_decryption(server_keypair):
    _, server_pub_bytes = server_keypair
    wrong_server_priv = x25519.X25519PrivateKey.generate()
    raw_payload = b"payload for wrong key"

    sealed = seal_payload(
        payload_bytes=raw_payload,
        server_public_key_bytes=server_pub_bytes,
        key_id="key_v1",
        device_id="dev-01",
        request_id="req-1",
    )

    with pytest.raises(EnvelopeTamperingError, match="AEAD authentication tag mismatch"):
        open_payload(
            envelope_bytes=sealed,
            server_private_key=wrong_server_priv,
        )
