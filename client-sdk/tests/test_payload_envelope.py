# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_payload_envelope.py: Unit tests for client-sdk payload envelope sealing and unsealing.
"""

from __future__ import annotations

import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

from freqid_client.crypto.payload_envelope import (
    is_sealed_payload,
    open_payload,
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


def test_client_seal_and_open_roundtrip(server_keypair, device_keypair):
    server_priv, server_pub_bytes = server_keypair
    dev_priv, dev_pub = device_keypair
    raw_payload = os.urandom(1024)

    sealed = seal_payload(
        payload_bytes=raw_payload,
        server_public_key_bytes=server_pub_bytes,
        key_id="key_v1",
        device_id="dev-client-1",
        request_id="req-client-100",
        device_private_key=dev_priv,
    )

    assert is_sealed_payload(sealed)
    unsealed, aad = open_payload(
        envelope_bytes=sealed,
        server_private_key=server_priv,
        expected_device_id="dev-client-1",
        expected_request_id="req-client-100",
        device_public_key=dev_pub,
    )
    assert unsealed == raw_payload
    assert aad["format"] == "PF02"
