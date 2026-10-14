# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
freqid_client: Privacy-preserving edge client SDK for FreqID.
"""

__version__ = "0.1.0"

from freqid_client.align import (
    REFERENCE_5_POINTS,
    align_face,
    estimate_similarity_transform,
)
from freqid_client.auth import (
    Authenticator,
    NoAuth,
    StaticTokenAuthenticator,
    load_device_credentials,
    save_device_credentials,
)
from freqid_client.camera import (
    CameraSource,
    ImageFolderSource,
    SingleImageSource,
    WebcamSource,
)
from freqid_client.config import ClientConfig
from freqid_client.detect import (
    FaceDetection,
    FaceDetector,
    YuNetFaceDetector,
)
from freqid_client.enroll import (
    EnrollmentCoordinator,
    EnrollmentProgress,
)
from freqid_client.errors import (
    AlignmentError,
    AuthenticationError,
    CameraError,
    ConfigurationError,
    DetectionError,
    FreqIDClientError,
    QualityGateRejectedError,
    ServerRejectedError,
    TransportError,
)
from freqid_client.pipeline import (
    ClientPipeline,
    PipelineResult,
    PipelineTimings,
)
from freqid_client.quality import (
    QualityGate,
    QualityReport,
)
from freqid_client.transport import FreqIDTransport

__all__ = [
    "REFERENCE_5_POINTS",
    "AlignmentError",
    "AuthenticationError",
    "Authenticator",
    "CameraError",
    "CameraSource",
    "ClientConfig",
    "ClientPipeline",
    "ConfigurationError",
    "DetectionError",
    "EnrollmentCoordinator",
    "EnrollmentProgress",
    "FaceDetection",
    "FaceDetector",
    "FreqIDClientError",
    "FreqIDTransport",
    "ImageFolderSource",
    "NoAuth",
    "PipelineResult",
    "PipelineTimings",
    "QualityGate",
    "QualityGateRejectedError",
    "QualityReport",
    "ServerRejectedError",
    "SingleImageSource",
    "StaticTokenAuthenticator",
    "TransportError",
    "WebcamSource",
    "YuNetFaceDetector",
    "__version__",
    "align_face",
    "estimate_similarity_transform",
    "load_device_credentials",
    "save_device_credentials",
]
