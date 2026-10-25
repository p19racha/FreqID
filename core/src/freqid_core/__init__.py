# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
freqid_core: Privacy-preserving face recognition core inference library.
"""

from typing import Any

__version__ = "0.1.0"

from freqid_core.config import InferenceConfig, ModelConfig, TransformConfig
from freqid_core.errors import (
    BackendNotAvailableError,
    CheckpointLoadError,
    DimensionMismatchError,
    FreqIDError,
    InvalidPayloadError,
    IsolationViolationError,
    ShapeMismatchError,
)
from freqid_core.matching import (
    MatchResult,
    compute_decision_threshold,
    cosine_similarity,
    identify,
    verify,
)
from freqid_core.payload import (
    PartialFacePayload,
    typical_payload_size,
)

__all__ = [
    "BackendNotAvailableError",
    "CheckpointLoadError",
    "DimensionMismatchError",
    "Embedder",
    "FreqIDError",
    "IR_18_Partial",
    "InferenceConfig",
    "InvalidPayloadError",
    "IsolationViolationError",
    "MatchResult",
    "ModelConfig",
    "ModelInfo",
    "PartialFacePayload",
    "ShapeMismatchError",
    "TransformConfig",
    "__version__",
    "batch_images_to_partial_frequency",
    "compute_decision_threshold",
    "cosine_similarity",
    "export_to_onnx",
    "identify",
    "image_to_partial_frequency",
    "typical_payload_size",
    "verify",
    "verify_onnx_export",
]


# Lazy attribute loader (PEP 562) to maintain strict architectural isolation:
# Ensures that importing freqid_core or server modules does NOT proactively load
# client-side image transformation libraries (torchjpeg, cv2, PIL).
def __getattr__(name: str) -> Any:
    if name in ("Embedder", "ModelInfo"):
        from freqid_core.embedder import Embedder, ModelInfo

        return Embedder if name == "Embedder" else ModelInfo
    elif name == "IR_18_Partial":
        from freqid_core.model import IR_18_Partial

        return IR_18_Partial
    elif name in ("image_to_partial_frequency", "batch_images_to_partial_frequency"):
        from freqid_core import transform

        return getattr(transform, name)
    elif name in ("export_to_onnx", "verify_onnx_export"):
        from freqid_core import export_onnx

        return getattr(export_onnx, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
