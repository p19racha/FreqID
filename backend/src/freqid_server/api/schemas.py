# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
schemas.py: Pydantic request and response models for freqid-server.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class VerifyResponse(BaseModel):
    """Result of 1:1 biometric verification."""

    status: str = Field(default="success")
    request_id: str
    is_match: bool
    similarity: float | None = None
    threshold: float
    claimed_identity: str
    verified_identity: str | None = None
    device_id: str


class CandidateMatch(BaseModel):
    """Candidate match record in 1:N biometric identification."""

    user_id: str
    similarity: float | None = None
    rank: int
    is_match: bool


class IdentifyResponse(BaseModel):
    """Result of 1:N biometric identification."""

    status: str = Field(default="success")
    request_id: str
    is_match: bool
    top_candidate: CandidateMatch | None = None
    candidates: list[CandidateMatch] = Field(default_factory=list)


class EnrollResponse(BaseModel):
    """Result of multi-frame biometric enrollment."""

    status: str = Field(default="enrolled")
    user_id: str
    template_id: str
    frames_processed: int
    frames_accepted: int
    outliers_rejected: int
    quality_score: float = 0.95
    duplicate_warning: str | None = None


class UserStatusResponse(BaseModel):
    """Result of user activation or deactivation."""

    status: str
    user_id: str
    message: str


class UserExportResponse(BaseModel):
    """Export of user profile, template metadata, and audit events (never plaintext biometrics)."""

    user_id: str
    status: str
    created_at: str
    updated_at: str
    template_metadata: dict[str, Any] | None = None
    audit_events: list[dict[str, Any]] = Field(default_factory=list)


class ModelMigrationReportResponse(BaseModel):
    """Report on templates requiring re-enrollment across model versions."""

    active_model_version: str
    total_templates: int
    compatible_templates: int
    needs_reenrollment_count: int
    outdated_model_breakdown: dict[str, int] = Field(default_factory=dict)


class DeleteResponse(BaseModel):
    """Result of identity template deletion."""

    status: str = Field(default="deleted")
    user_id: str
    message: str


class ModelInfoResponse(BaseModel):
    """Public non-sensitive metadata for active server model."""

    model_version: str
    backend: str
    device: str
    embedding_dim: int
    input_channels: int
    checkpoint_sha256: str


class HealthResponse(BaseModel):
    """Liveness probe response."""

    status: str = "ok"
    service: str = "freqid-server"


class ReadyResponse(BaseModel):
    """Readiness probe response."""

    status: str = "ready"
    model_loaded: bool
    model_version: str
    backend: str
    device: str
    store_connected: bool
    enrolled_identities: int


class ErrorDetail(BaseModel):
    """Machine-readable error envelope."""

    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    """Standardized error response."""

    error: ErrorDetail


# -------------------------------------------------------------------------
# Phase 6 Admin and Device Schemas
# -------------------------------------------------------------------------


class AdminLoginRequest(BaseModel):
    username: str
    password: str
    totp_code: str | None = None


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    admin_id: str
    username: str
    role: str
    permissions: list[str]


class AdminProfileResponse(BaseModel):
    id: str
    username: str
    role: str
    is_active: bool
    totp_enabled: bool
    created_at: str
    permissions: list[str]


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class TotpSetupResponse(BaseModel):
    secret: str
    uri: str


class TotpVerifyRequest(BaseModel):
    code: str


class TotpVerifyResponse(BaseModel):
    status: str = "enabled"
    recovery_codes: list[str]


class AdminCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "operator"


class AdminUpdateRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None


class AdminSummary(BaseModel):
    id: str
    username: str
    role: str
    is_active: bool
    failed_logins: int
    locked_until: str | None = None
    created_at: str


class DevicePairRequest(BaseModel):
    token: str
    public_key: str
    name: str
    software_version: str | None = None


class DevicePairResponse(BaseModel):
    device_id: str
    state: str
    key_id: str
    server_time: str


class DeviceHeartbeatRequest(BaseModel):
    software_version: str = "0.1.0"
    camera_ok: bool = True
    uptime_seconds: float = 0.0
    queued_payloads: int = 0


class DeviceHeartbeatResponse(BaseModel):
    status: str = "ok"
    server_time: str
    state: str
    config: dict[str, Any] = Field(default_factory=dict)


class DeviceRotateKeyRequest(BaseModel):
    new_public_key: str


class DeviceRotateKeyResponse(BaseModel):
    status: str = "key_rotated"
    key_id: str


class PairingTokenCreateRequest(BaseModel):
    name_hint: str | None = None
    location_hint: str | None = None
    scopes: list[str] = Field(default_factory=lambda: ["verify"])
    expires_in_minutes: int = 15


class PairingTokenCreateResponse(BaseModel):
    id: str
    token: str
    expires_at: str
    scopes_allowed: list[str]


class DeviceSummary(BaseModel):
    id: str
    name: str
    location: str | None = None
    state: str
    scopes: list[str]
    key_id: str
    software_version: str | None = None
    last_seen: str | None = None
    created_at: str


class DeviceDetail(BaseModel):
    id: str
    name: str
    location: str | None = None
    state: str
    scopes: list[str]
    public_key: str
    key_id: str
    software_version: str | None = None
    approved_by: str | None = None
    last_seen: str | None = None
    revoked_at: str | None = None
    revocation_reason: str | None = None
    created_at: str
    recent_heartbeats: list[dict[str, Any]] = Field(default_factory=list)


class DeviceUpdateRequest(BaseModel):
    name: str | None = None
    location: str | None = None
    scopes: list[str] | None = None


class DeviceActionRequest(BaseModel):
    reason: str | None = None


class SystemSettingsResponse(BaseModel):
    settings: dict[str, Any]


class SystemSettingsUpdateRequest(BaseModel):
    settings: dict[str, Any]


class SystemStatusResponse(BaseModel):
    model_version: str
    gallery_size: int
    queue_depth: int
    device_counts: dict[str, int]
    devices_offline: int
    audit_queue_size: int


class AuditQueryResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    cursor: str | None = None


class SecurityStatusResponse(BaseModel):
    tls_min_version: str = "TLSv1.2"
    active_master_key_id: str
    key_hierarchy_configured: bool = True
    template_protection: dict[str, Any]
    payload_sealing: dict[str, Any]
    anomaly_detector: dict[str, Any]
