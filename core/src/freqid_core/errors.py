# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
errors.py: Typed exception hierarchy for freqid_core.
"""


class FreqIDError(Exception):
    """Base exception for all freqid_core errors."""


class InvalidPayloadError(FreqIDError):
    """Raised when wire payload format, magic bytes, or checksum is invalid or corrupted."""


class ShapeMismatchError(FreqIDError):
    """Raised when input array or tensor shape does not match expected model dimensions."""


class BackendNotAvailableError(FreqIDError):
    """Raised when the requested execution backend (e.g., onnxruntime) is not available."""


class CheckpointLoadError(FreqIDError):
    """Raised when model weights checkpoint cannot be parsed or has missing/unexpected keys."""


class DimensionMismatchError(FreqIDError):
    """Raised when embedding dimensions do not match during vector matching."""


class IsolationViolationError(FreqIDError):
    """Raised when server-side components attempt to load client-only raw image modules."""
