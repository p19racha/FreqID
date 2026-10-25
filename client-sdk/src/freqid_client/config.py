# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
config.py: Configuration dataclasses and YAML loading with environment variable overrides.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from freqid_client.errors import ConfigurationError

DEFAULT_YUNET_MODEL_PATH = str(
    Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"
)


@dataclass
class ClientConfig:
    """Configuration settings for freqid-client edge SDK."""

    # Server & Transport
    server_url: str = "http://localhost:8000"
    device_id: str = "dev_default"
    auth_token: str | None = None
    ca_cert_path: str | None = None
    client_cert_path: str | None = None
    client_key_path: str | None = None
    pinned_cert_fingerprint: str | None = None
    insecure_skip_verify: bool = False
    request_timeout_seconds: float = 10.0
    max_retries: int = 3

    # Camera & Capture
    camera_index: int = 0
    camera_width: int = 640
    camera_height: int = 480
    camera_fps: int = 30

    # Detection & Alignment
    detector_model_path: str = DEFAULT_YUNET_MODEL_PATH
    detector_score_threshold: float = 0.6
    detector_nms_threshold: float = 0.3
    crop_size: tuple[int, int] = (112, 112)

    # Quality Gate
    allow_multiple_faces: bool = False
    min_face_size: int = 60
    min_laplacian_var: float = 80.0
    min_brightness: float = 40.0
    max_brightness: float = 220.0
    max_yaw_angle: float = 15.0

    # Privacy & Debugging
    debug_save_dir: str | None = None
    compress_payload: bool = True

    # Application-Layer Payload Sealing (Phase 8)
    seal_payloads: bool = False
    server_payload_public_key_hex: str | None = None
    payload_key_id: str | None = None

    def __post_init__(self) -> None:
        if self.debug_save_dir:
            print(
                f"[WARNING: PRIVACY ALERT] --debug-save-dir is enabled ({self.debug_save_dir}). "
                "Raw facial imagery will be written to disk. DO NOT USE IN PRODUCTION ENVIRONMENTS.",
                file=sys.stderr,
            )
        if self.insecure_skip_verify:
            print(
                "[WARNING: SECURITY ALERT] insecure_skip_verify is True. "
                "TLS certificate validation is disabled. Vulnerable to MITM attacks.",
                file=sys.stderr,
            )

    @classmethod
    def from_yaml(cls, path: str | Path) -> ClientConfig:
        """Load configuration from a YAML file, applying environment variable overrides."""
        p = Path(path)
        if not p.is_file():
            raise ConfigurationError(f"Config file not found: {path}")

        try:
            with open(p, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            raise ConfigurationError(f"Failed to parse YAML file {path}: {e}") from e

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClientConfig:
        """Builds configuration with environment variable overrides."""
        cfg = cls()

        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)

        # Environment variable overrides
        if os.getenv("FREQID_SERVER_URL"):
            cfg.server_url = os.environ["FREQID_SERVER_URL"]
        if os.getenv("FREQID_DEVICE_ID"):
            cfg.device_id = os.environ["FREQID_DEVICE_ID"]
        if os.getenv("FREQID_AUTH_TOKEN"):
            cfg.auth_token = os.environ["FREQID_AUTH_TOKEN"]
        if os.getenv("FREQID_CA_CERT_PATH"):
            cfg.ca_cert_path = os.environ["FREQID_CA_CERT_PATH"]
        if os.getenv("FREQID_CLIENT_CERT_PATH"):
            cfg.client_cert_path = os.environ["FREQID_CLIENT_CERT_PATH"]
        if os.getenv("FREQID_CLIENT_KEY_PATH"):
            cfg.client_key_path = os.environ["FREQID_CLIENT_KEY_PATH"]
        if os.getenv("FREQID_PINNED_CERT_FINGERPRINT"):
            cfg.pinned_cert_fingerprint = os.environ["FREQID_PINNED_CERT_FINGERPRINT"]
        if os.getenv("FREQID_INSECURE_SKIP_VERIFY"):
            cfg.insecure_skip_verify = os.environ["FREQID_INSECURE_SKIP_VERIFY"].lower() in (
                "1",
                "true",
                "yes",
            )
        if os.getenv("FREQID_CAMERA_INDEX"):
            try:
                cfg.camera_index = int(os.environ["FREQID_CAMERA_INDEX"])
            except ValueError:
                pass
        if os.getenv("FREQID_DEBUG_SAVE_DIR"):
            cfg.debug_save_dir = os.environ["FREQID_DEBUG_SAVE_DIR"]

        cfg.__post_init__()
        return cfg
