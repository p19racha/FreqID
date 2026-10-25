# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
payload.py: Versioned binary wire format for partial frequency payloads.

This module is completely independent of PyTorch and image libraries. It operates
strictly using NumPy and Python's standard library (struct, zlib). Both client devices
and central servers use this module to serialize and deserialize frequency representations.
"""

from __future__ import annotations

import struct
import zlib

import numpy as np

from freqid_core.errors import InvalidPayloadError, ShapeMismatchError

MAGIC_BYTES = b"FQID"
PAYLOAD_VERSION = 1
FLAG_UNCOMPRESSED = 0
FLAG_ZLIB_COMPRESSED = 1

# Header: 28 bytes
# <4s : Magic (FQID)
#  H  : Version (uint16)
#  H  : Flags (uint16: 0=raw, 1=compressed)
#  I  : Batch size (uint32)
#  H  : Channels (uint16, 27)
#  H  : Height (uint16, 112)
#  H  : Width (uint16, 112)
#  B  : Dtype code (uint8: 0=float32, 1=float16)
#  b  : Subset index (int8: -1 for anonymous/unspecified)
#  b  : Permutation index (int8: -1 for anonymous/unspecified)
#  3s : Reserved padding
#  I  : Data length in bytes (uint32)
HEADER_FORMAT = "<4sHH IHHH Bbb3s I"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
CHECKSUM_SIZE = 4
MAX_PAYLOAD_SIZE = 64 * 1024 * 1024  # 64 MB maximum safe limit


class PartialFacePayload:
    """
    Encapsulates a partial frequency representation for network transmission and verification.
    """

    def __init__(
        self,
        data: np.ndarray,
        subset_index: int = -1,
        perm_index: int = -1,
        version: int = PAYLOAD_VERSION,
    ) -> None:
        """
        Initialize a PartialFacePayload.

        Args:
            data: NumPy array of shape (27, 112, 112) or (B, 27, 112, 112), dtype float32 or float16.
            subset_index: Optional subset index [0..5], or -1 if anonymous.
            perm_index: Optional permutation index [0..2], or -1 if anonymous.
            version: Payload protocol version (default: 1).
        """
        if not isinstance(data, np.ndarray):
            raise TypeError(f"Payload data must be a numpy.ndarray, got {type(data).__name__}")

        # Normalize 3D tensor (27, 112, 112) to 4D batch (1, 27, 112, 112) internally
        if data.ndim == 3:
            if data.shape != (27, 112, 112):
                raise ShapeMismatchError(f"Expected shape (27, 112, 112), got {data.shape}")
            self._data = np.ascontiguousarray(data[np.newaxis, ...])
            self._is_single = True
        elif data.ndim == 4:
            if data.shape[1:] != (27, 112, 112):
                raise ShapeMismatchError(f"Expected shape (B, 27, 112, 112), got {data.shape}")
            self._data = np.ascontiguousarray(data)
            self._is_single = False
        else:
            raise ShapeMismatchError(
                f"Expected 3D or 4D array, got {data.ndim}D array with shape {data.shape}"
            )

        if self._data.dtype not in (np.float32, np.float16):
            raise TypeError(f"Payload dtype must be float32 or float16, got {self._data.dtype}")

        if not np.isfinite(self._data).all():
            raise InvalidPayloadError("Payload contains non-finite values (NaN or Inf)")

        self.subset_index = int(subset_index)
        self.perm_index = int(perm_index)
        self.version = int(version)

    @property
    def data(self) -> np.ndarray:
        """Returns the array: 3D if initialized with 3D, otherwise 4D batch."""
        return self._data[0] if self._is_single else self._data

    @property
    def batch_data(self) -> np.ndarray:
        """Always returns 4D batch of shape (B, 27, 112, 112)."""
        return self._data

    @property
    def shape(self) -> tuple[int, ...]:
        return self.data.shape

    @property
    def batch_size(self) -> int:
        return self._data.shape[0]

    @property
    def dtype(self) -> np.dtype:
        return self._data.dtype

    def byte_size(self) -> int:
        """Returns the memory size in bytes of the underlying frequency array."""
        return self._data.nbytes

    def to_bytes(self, compress: bool = False) -> bytes:
        """
        Serialize payload to binary wire format.

        Args:
            compress: If True, compresses the raw frequency buffer using zlib.

        Returns:
            bytes containing header, buffer, and trailing CRC32 checksum.
        """
        raw_bytes = self._data.tobytes()
        dtype_code = 0 if self._data.dtype == np.float32 else 1

        if compress:
            data_bytes = zlib.compress(raw_bytes, level=6)
            flags = FLAG_ZLIB_COMPRESSED
        else:
            data_bytes = raw_bytes
            flags = FLAG_UNCOMPRESSED

        data_len = len(data_bytes)
        b, c, h, w = self._data.shape

        header = struct.pack(
            HEADER_FORMAT,
            MAGIC_BYTES,
            self.version,
            flags,
            b,
            c,
            h,
            w,
            dtype_code,
            self.subset_index,
            self.perm_index,
            b"\x00\x00\x00",
            data_len,
        )

        checksum = zlib.crc32(data_bytes)
        checksum_bytes = struct.pack("<I", checksum)

        return header + data_bytes + checksum_bytes

    @classmethod
    def from_bytes(cls, raw_bytes: bytes) -> PartialFacePayload:
        """
        Deserialize and strictly validate a PartialFacePayload from binary bytes.

        Raises:
            InvalidPayloadError: If format, version, length, checksum, or contents are invalid.
            ShapeMismatchError: If tensor dimensions do not match PartialFace specifications.
        """
        if not isinstance(raw_bytes, (bytes, bytearray)):
            raise TypeError(f"Expected bytes, got {type(raw_bytes).__name__}")

        total_len = len(raw_bytes)
        if total_len < HEADER_SIZE + CHECKSUM_SIZE:
            raise InvalidPayloadError(
                f"Payload too short: {total_len} bytes, minimum required {HEADER_SIZE + CHECKSUM_SIZE}"
            )

        if total_len > MAX_PAYLOAD_SIZE:
            raise InvalidPayloadError(
                f"Payload size {total_len} exceeds maximum allowed limit {MAX_PAYLOAD_SIZE}"
            )

        (
            magic,
            version,
            flags,
            batch_size,
            channels,
            height,
            width,
            dtype_code,
            subset_index,
            perm_index,
            _reserved,
            data_len,
        ) = struct.unpack(HEADER_FORMAT, raw_bytes[:HEADER_SIZE])

        if magic != MAGIC_BYTES:
            raise InvalidPayloadError(
                f"Invalid magic bytes: expected {MAGIC_BYTES!r}, got {magic!r}"
            )

        if version != PAYLOAD_VERSION:
            raise InvalidPayloadError(f"Unsupported payload version: {version}")

        if channels != 27 or height != 112 or width != 112:
            raise ShapeMismatchError(
                f"Invalid dimensions in header: channels={channels}, height={height}, width={width}. "
                f"Expected (27, 112, 112)."
            )

        if total_len != HEADER_SIZE + data_len + CHECKSUM_SIZE:
            raise InvalidPayloadError(
                f"Corrupted payload: expected total size {HEADER_SIZE + data_len + CHECKSUM_SIZE}, "
                f"got {total_len}"
            )

        data_bytes = raw_bytes[HEADER_SIZE : HEADER_SIZE + data_len]
        stored_checksum = struct.unpack("<I", raw_bytes[HEADER_SIZE + data_len :])[0]
        computed_checksum = zlib.crc32(data_bytes)

        if computed_checksum != stored_checksum:
            raise InvalidPayloadError(
                f"Checksum mismatch: header indicated CRC32 {stored_checksum}, computed {computed_checksum}"
            )

        if flags & FLAG_ZLIB_COMPRESSED:
            try:
                uncompressed_bytes = zlib.decompress(data_bytes)
            except Exception as e:
                raise InvalidPayloadError(f"Decompression failed: {e}") from e
        else:
            uncompressed_bytes = data_bytes

        dtype = np.float32 if dtype_code == 0 else np.float16
        expected_bytes = batch_size * channels * height * width * np.dtype(dtype).itemsize

        if len(uncompressed_bytes) != expected_bytes:
            raise InvalidPayloadError(
                f"Decompressed byte length {len(uncompressed_bytes)} does not match expected {expected_bytes}"
            )

        array = np.frombuffer(uncompressed_bytes, dtype=dtype).reshape(
            (batch_size, channels, height, width)
        )

        # Check for NaNs and Infs
        if not np.isfinite(array).all():
            raise InvalidPayloadError("Payload contains non-finite values (NaN or Inf)")

        # Return single 3D if batch_size == 1
        return cls(
            data=array[0] if batch_size == 1 else array,
            subset_index=subset_index,
            perm_index=perm_index,
            version=version,
        )


def typical_payload_size(compress: bool = False, fp16: bool = False) -> int:
    """
    Returns the expected wire size in bytes for a single face payload (batch_size=1).
    """
    dtype = np.float16 if fp16 else np.float32
    raw_array_bytes = 1 * 27 * 112 * 112 * np.dtype(dtype).itemsize
    if not compress:
        return HEADER_SIZE + raw_array_bytes + CHECKSUM_SIZE
    # Estimated compressed size based on DCT high-frequency sparsity
    return HEADER_SIZE + int(raw_array_bytes * 0.35) + CHECKSUM_SIZE
