# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_payload.py: Unit tests for binary wire format, validation, and serialization.
"""

import numpy as np
import pytest

from freqid_core.errors import InvalidPayloadError, ShapeMismatchError
from freqid_core.payload import (
    HEADER_SIZE,
    PartialFacePayload,
    typical_payload_size,
)


def test_payload_roundtrip_raw():
    data = np.random.randn(27, 112, 112).astype(np.float32)
    payload = PartialFacePayload(data, subset_index=2, perm_index=1)

    raw_bytes = payload.to_bytes(compress=False)
    assert len(raw_bytes) == typical_payload_size(compress=False, fp16=False)

    restored = PartialFacePayload.from_bytes(raw_bytes)
    assert restored.shape == (27, 112, 112)
    assert restored.subset_index == 2
    assert restored.perm_index == 1
    assert restored.version == 1
    np.testing.assert_array_equal(restored.data, data)


def test_payload_roundtrip_compressed():
    data = np.random.randn(27, 112, 112).astype(np.float32)
    payload = PartialFacePayload(data, subset_index=0, perm_index=0)

    compressed_bytes = payload.to_bytes(compress=True)
    # Compressed bytes should be smaller than raw array
    assert len(compressed_bytes) < payload.byte_size()

    restored = PartialFacePayload.from_bytes(compressed_bytes)
    assert restored.shape == (27, 112, 112)
    np.testing.assert_array_equal(restored.data, data)


def test_payload_batch_roundtrip():
    data = np.random.randn(3, 27, 112, 112).astype(np.float32)
    payload = PartialFacePayload(data)
    assert payload.batch_size == 3

    raw_bytes = payload.to_bytes()
    restored = PartialFacePayload.from_bytes(raw_bytes)
    assert restored.batch_size == 3
    assert restored.shape == (3, 27, 112, 112)
    np.testing.assert_array_equal(restored.data, data)


def test_payload_rejects_corrupted_magic():
    data = np.random.randn(27, 112, 112).astype(np.float32)
    payload = PartialFacePayload(data)
    raw_bytes = bytearray(payload.to_bytes())

    # Corrupt magic bytes
    raw_bytes[:4] = b"BAD!"
    with pytest.raises(InvalidPayloadError, match="Invalid magic bytes"):
        PartialFacePayload.from_bytes(bytes(raw_bytes))


def test_payload_rejects_corrupted_checksum():
    data = np.random.randn(27, 112, 112).astype(np.float32)
    payload = PartialFacePayload(data)
    raw_bytes = bytearray(payload.to_bytes())

    # Flip a bit in the data buffer
    raw_bytes[HEADER_SIZE + 10] ^= 0xFF
    with pytest.raises(InvalidPayloadError, match="Checksum mismatch"):
        PartialFacePayload.from_bytes(bytes(raw_bytes))


def test_payload_rejects_nan_and_inf():
    data = np.random.randn(27, 112, 112).astype(np.float32)
    data[0, 0, 0] = np.nan
    with pytest.raises(InvalidPayloadError, match="non-finite"):
        PartialFacePayload(data)

    data[0, 0, 0] = np.inf
    with pytest.raises(InvalidPayloadError, match="non-finite"):
        PartialFacePayload(data)


def test_payload_rejects_wrong_shape():
    # 3-channel raw image array
    bad_data = np.random.randn(3, 112, 112).astype(np.float32)
    with pytest.raises(ShapeMismatchError):
        PartialFacePayload(bad_data)
