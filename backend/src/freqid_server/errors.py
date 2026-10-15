# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
errors.py: Typed exception hierarchy for freqid-server.
"""

from __future__ import annotations


class FreqIDServerError(Exception):
    """Base exception for all freqid-server errors."""

    def __init__(self, message: str, error_code: str = "INTERNAL_SERVER_ERROR", status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code


class InvalidPayloadError(FreqIDServerError):
    """Raised when an incoming partial frequency payload fails validation."""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, error_code="INVALID_PAYLOAD", status_code=400)


class ImageDataRejectedError(FreqIDServerError):
    """Raised when spatial image bytes (JPEG, PNG, etc.) are detected in request body."""

    def __init__(self, message: str = "Raw spatial image data is prohibited. Only partial frequency payloads are accepted.") -> None:
        super().__init__(message=message, error_code="IMAGE_DATA_REJECTED", status_code=400)


class ReplayDetectedError(FreqIDServerError):
    """Raised when a request nonce has already been consumed."""

    def __init__(self, message: str = "Cryptographic nonce has already been consumed or is expired.") -> None:
        super().__init__(message=message, error_code="REPLAY_DETECTED", status_code=400)


class ModelVersionMismatchError(FreqIDServerError):
    """Raised when a payload or stored template version does not match active server model."""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, error_code="MODEL_VERSION_MISMATCH", status_code=400)


class AuthenticationError(FreqIDServerError):
    """Raised when credentials are missing, malformed, or invalid."""

    def __init__(self, message: str = "Authentication failed or token missing.") -> None:
        super().__init__(message=message, error_code="UNAUTHORIZED", status_code=401)


class InsufficientScopeError(FreqIDServerError):
    """Raised when an authenticated principal lacks required scope for an endpoint."""

    def __init__(self, message: str = "Principal lacks required permission scope.") -> None:
        super().__init__(message=message, error_code="INSUFFICIENT_SCOPE", status_code=403)


class UserNotFoundError(FreqIDServerError):
    """Raised when an identity template is not found in the store."""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, error_code="USER_NOT_FOUND", status_code=404)


class PayloadTooLargeError(FreqIDServerError):
    """Raised when request payload exceeds maximum permitted byte size."""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, error_code="PAYLOAD_TOO_LARGE", status_code=413)


class UnsupportedMediaTypeError(FreqIDServerError):
    """Raised when request Content-Type is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, error_code="UNSUPPORTED_MEDIA_TYPE", status_code=415)


class RateLimitExceededError(FreqIDServerError):
    """Raised when rate limit or repeated failed verification threshold is exceeded."""

    def __init__(self, message: str = "Rate limit exceeded. Please back off.", retry_after: int = 5) -> None:
        super().__init__(message=message, error_code="RATE_LIMIT_EXCEEDED", status_code=429)
        self.retry_after = retry_after


class InferenceQueueFullError(FreqIDServerError):
    """Raised when the bounded inference queue is saturated."""

    def __init__(self, message: str = "Inference server is at capacity. Please retry shortly.", retry_after: int = 1) -> None:
        super().__init__(message=message, error_code="INFERENCE_QUEUE_FULL", status_code=503)
        self.retry_after = retry_after


class InferenceTimeoutError(FreqIDServerError):
    """Raised when forward embedding inference exceeds timeout budget."""

    def __init__(self, message: str = "Inference execution timed out.") -> None:
        super().__init__(message=message, error_code="INFERENCE_TIMEOUT", status_code=504)


class OptimisticLockError(FreqIDServerError):
    """Raised when concurrent template modification violates optimistic lock version."""

    def __init__(self, message: str = "Template was modified concurrently by another transaction.") -> None:
        super().__init__(message=message, error_code="OPTIMISTIC_LOCK_CONFLICT", status_code=409)


class StorageError(FreqIDServerError):
    """Raised when database or storage backend operation fails."""

    def __init__(self, message: str = "Storage operation failed.") -> None:
        super().__init__(message=message, error_code="STORAGE_ERROR", status_code=500)


class DuplicateIdentityError(FreqIDServerError):
    """Raised when an identity is already enrolled or duplicate biometrics are detected."""

    def __init__(self, message: str = "Biometric identity is already enrolled or duplicates existing identity.") -> None:
        super().__init__(message=message, error_code="DUPLICATE_IDENTITY", status_code=409)


class ValidationError(FreqIDServerError):
    """Raised when request parameters or passwords fail validation rules."""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, error_code="VALIDATION_ERROR", status_code=400)


class DeviceRevokedError(FreqIDServerError):
    """Raised when a permanently revoked device attempts authentication."""

    def __init__(self, message: str = "Device has been permanently revoked.") -> None:
        super().__init__(message=message, error_code="DEVICE_REVOKED", status_code=403)


class DeviceSuspendedError(FreqIDServerError):
    """Raised when a suspended device attempts authentication."""

    def __init__(self, message: str = "Device is currently suspended.") -> None:
        super().__init__(message=message, error_code="DEVICE_SUSPENDED", status_code=403)


class AccountDisabledError(FreqIDServerError):
    """Raised when a disabled admin or user account attempts action."""

    def __init__(self, message: str = "Account is disabled.") -> None:
        super().__init__(message=message, error_code="ACCOUNT_DISABLED", status_code=403)


class AccountLockedError(FreqIDServerError):
    """Raised when an account is locked due to repeated failed logins."""

    def __init__(self, message: str, retry_after: int = 900) -> None:
        super().__init__(message=message, error_code="ACCOUNT_LOCKED", status_code=423)
        self.retry_after = retry_after

