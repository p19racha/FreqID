# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
freqid_client.crypto package.
"""

from freqid_client.crypto.payload_envelope import (
    MAGIC_V2,
    DeviceBindingError,
    EnvelopeTamperingError,
    ExpiredPayloadError,
    PayloadEnvelopeError,
    ReplayAttackError,
    is_sealed_payload,
    open_payload,
    seal_payload,
)

__all__ = [
    "MAGIC_V2",
    "DeviceBindingError",
    "EnvelopeTamperingError",
    "ExpiredPayloadError",
    "PayloadEnvelopeError",
    "ReplayAttackError",
    "is_sealed_payload",
    "open_payload",
    "seal_payload",
]
