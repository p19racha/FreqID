# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
errors.py: Typed exception hierarchy for freqid_client.
"""


class FreqIDClientError(Exception):
    """Base exception for all freqid_client errors."""


class ConfigurationError(FreqIDClientError):
    """Raised when configuration parameters or file cannot be parsed or are invalid."""


class CameraError(FreqIDClientError):
    """Raised when camera hardware cannot be opened or fails to read frames."""


class DetectionError(FreqIDClientError):
    """Raised when face detection backend fails to initialize or process frames."""


class QualityGateRejectedError(FreqIDClientError):
    """Raised when a captured face frame fails quality gate requirements."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"[{reason_code}] {message}")
        self.reason_code = reason_code


class AlignmentError(FreqIDClientError):
    """Raised when 5-point facial landmark alignment fails."""


class TransportError(FreqIDClientError):
    """Raised on network failure, timeout, or HTTP communication errors with server."""


class ServerRejectedError(TransportError):
    """Raised when server explicitly rejects request with error code (e.g. INVALID_PAYLOAD)."""

    def __init__(self, error_code: str, message: str, status_code: int = 400) -> None:
        super().__init__(f"Server rejected request ({error_code}, status {status_code}): {message}")
        self.error_code = error_code
        self.status_code = status_code


class AuthenticationError(TransportError):
    """Raised when device credentials are missing, expired, or invalid (401/403)."""
