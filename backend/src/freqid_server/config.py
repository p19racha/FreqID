# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
config.py: Server configuration management via pydantic-settings and YAML.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerConfig(BaseSettings):
    """
    Central configuration for freqid-server.
    Precedence: explicit kwargs > FREQID_SERVER_* environment variables > YAML > defaults.
    """

    model_config = SettingsConfigDict(
        env_prefix="FREQID_SERVER_",
        env_file=".env",
        extra="ignore",
    )

    # Server Network Binding
    host: str = Field(default="0.0.0.0", description="Network interface to bind")
    port: int = Field(default=8000, description="Network port to bind")
    environment: str = Field(
        default="development", description="'development', 'test', or 'production'"
    )

    # Model & Inference Settings
    model_path: str = Field(
        default="research/outputs/checkpoints/partialface_ir_18.onnx",
        description="Path to ONNX or PyTorch model checkpoint",
    )
    model_backend: Literal["onnx", "torch"] = Field(default="onnx", description="'onnx' or 'torch'")
    model_version: str = Field(default="v1.0-ir18", description="Semantic model version identifier")
    device: str = Field(default="cpu", description="'cpu' or 'cuda'")

    # Biometric Decisions & Thresholds
    decision_threshold: float = Field(
        default=0.35,
        description="Decision operating threshold for 1:1 verify and 1:N identify",
    )
    identify_score_floor: float = Field(
        default=0.20,
        description="Minimum similarity floor for candidates returned in 1:N identify",
    )
    enroll_outlier_threshold: float = Field(
        default=0.30,
        description="Minimum pairwise similarity required among enrollment samples",
    )

    # Payload & Buffer Limits
    max_single_payload_bytes: int = Field(
        default=2 * 1024 * 1024,
        description="Maximum permissible byte size for a single PartialFacePayload (default: 2 MB)",
    )
    max_batch_payload_bytes: int = Field(
        default=15 * 1024 * 1024,
        description="Maximum permissible byte size for multi-frame enrollment batch (default: 15 MB)",
    )
    max_enroll_frames: int = Field(
        default=10,
        description="Maximum number of frames accepted in a single enrollment batch",
    )

    # Concurrency & Queueing
    max_inference_workers: int = Field(
        default=4,
        description="Size of ThreadPoolExecutor worker pool for model inference",
    )
    max_queue_size: int = Field(
        default=64,
        description="Maximum capacity of bounded inference queue before HTTP 503 load shedding",
    )
    inference_timeout_seconds: float = Field(
        default=5.0,
        description="Timeout budget for a single forward inference execution",
    )

    # Security & Access Control
    mask_scores_in_production: bool = Field(
        default=True,
        description="Conceal floating-point scores from non-admin callers to thwart hill-climbing attacks",
    )
    allow_static_tokens_in_production: bool = Field(
        default=False,
        description="Require explicit override to permit static bearer tokens in production mode",
    )
    static_tokens: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "dev_verify_token": ["verify"],
            "dev_kiosk_token": ["verify", "identify"],
            "dev_admin_token": ["verify", "identify", "enroll", "admin"],
        },
        description="Mapping of static bearer tokens to authorized permission scopes",
    )
    nonce_ttl_seconds: int = Field(
        default=300,
        description="Sliding window TTL in seconds for cryptographic nonce deduplication",
    )

    # Storage & Persistence
    storage_backend: str = Field(
        default="postgres",
        description="'postgres' or 'memory'",
    )
    database_url: str = Field(
        default="postgresql+asyncpg://freqid_app:freqid_app_dev_secret@127.0.0.1:54322/freqid",
        description="PostgreSQL connection string (asyncpg)",
    )
    database_pool_size: int = Field(
        default=10,
        description="SQLAlchemy connection pool size",
    )
    database_max_overflow: int = Field(
        default=20,
        description="SQLAlchemy connection pool max overflow",
    )
    database_pool_timeout: float = Field(
        default=30.0,
        description="SQLAlchemy connection pool timeout in seconds",
    )
    database_pool_pre_ping: bool = Field(
        default=True,
        description="Enable connection liveness ping on checkout",
    )
    database_echo_sql: bool = Field(
        default=False,
        description="Echo SQL statements (strictly False in production to prevent parameter leak)",
    )
    sqlite_db_path: str = Field(
        default="",
        description="Optional SQLite file path for dev template persistence across restarts",
    )
    openapi_output_path: str = Field(
        default="backend/openapi.json",
        description="Target output path when exporting OpenAPI 3.1 specification",
    )
    cors_origins: list[str] = Field(
        default_factory=list,
        description="Permitted CORS origins (default: empty / CORS disabled)",
    )

    # Master Key Encryption-at-Rest
    master_key: str = Field(
        default="MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE=",
        description="Base64 encoded 256-bit master encryption key",
    )
    master_key_file: str = Field(
        default="",
        description="Path to POSIX 0600 file containing base64 master key",
    )
    active_key_id: str = Field(
        default="key_v1",
        description="Active master key identifier for new encryptions",
    )

    # Enrollment Lifecycle & Capacity Limits
    max_enrolled_users: int = Field(
        default=100000,
        description="Maximum permitted enrolled users guardrail",
    )
    enroll_duplicate_check_policy: str = Field(
        default="warn",
        description="'disabled', 'warn', or 'block'",
    )
    enroll_duplicate_threshold: float = Field(
        default=0.60,
        description="Cosine similarity threshold flagging possible duplicate identity",
    )

    # Audit Logging
    audit_enable_hash_chain: bool = Field(
        default=False,
        description="Enable cryptographic tamper-evident hash chaining in audit table",
    )
    audit_retention_days: int = Field(
        default=90,
        description="Default retention period in days for audit records",
    )

    # Rate Limiting & Brute-Force Lockout
    rate_limit_per_minute: int = Field(
        default=120,
        description="Maximum requests per minute per IP / principal",
    )
    max_failed_verifications_lockout: int = Field(
        default=5,
        description="Consecutive failed verification attempts on a user ID before lockout",
    )
    lockout_duration_seconds: int = Field(
        default=60,
        description="Lockout duration in seconds for repeatedly failing user identities",
    )

    @property
    def storage_path(self) -> str:
        return self.sqlite_db_path

    @property
    def max_failed_attempts_lockout(self) -> int:
        return self.max_failed_verifications_lockout

    @property
    def enroll_max_frames(self) -> int:
        return self.max_enroll_frames

    @classmethod
    def from_yaml(cls, yaml_path: str | Path) -> ServerConfig:
        """Loads configuration from a YAML file, overlaid with environment variables."""
        p = Path(yaml_path)
        if not p.is_file():
            raise FileNotFoundError(f"Configuration file not found: {yaml_path}")
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(**data)


def load_config(config_path: str | Path | None = None, **overrides: Any) -> ServerConfig:
    """
    Loads ServerConfig with priority: overrides > explicit config_path > FREQID_CONFIG env > defaults.
    """
    path = config_path or os.environ.get("FREQID_CONFIG")
    if path:
        cfg = ServerConfig.from_yaml(path)
        if overrides:
            for k, v in overrides.items():
                setattr(cfg, k, v)
        return cfg
    return ServerConfig(**overrides)
