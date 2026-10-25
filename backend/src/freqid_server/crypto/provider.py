# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
provider.py: Pluggable master key provider interface and file/environment implementation.
"""

from __future__ import annotations

import base64
import os
import stat
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.keywrap import (
    InvalidUnwrap,
    aes_key_unwrap,
    aes_key_wrap,
)


@dataclass(frozen=True)
class KeyHierarchy:
    master_key_id: str
    template_key: bytes
    transform_key: bytes
    audit_key: bytes
    token_key: bytes
    payload_private_key: x25519.X25519PrivateKey
    payload_public_key_bytes: bytes


class KeyProvider(ABC):
    """
    Abstract interface for master key management.
    Phase 5 provides EnvOrFileKeyProvider.
    Phase 8 will introduce KMS and HSM hardware providers behind this interface.
    """

    @abstractmethod
    def get_key(self, key_id: str) -> bytes:
        """Retrieves raw 256-bit master key by key_id."""

    @abstractmethod
    def current_key_id(self) -> str:
        """Returns the active key identifier for new encryptions."""

    def wrap_key(self, dek: bytes, key_id: str | None = None) -> bytes:
        """Wraps a 256-bit Data Encryption Key (DEK) using AES Key Wrap (RFC 3394)."""
        target_id = key_id or self.current_key_id()
        kek = self.get_key(target_id)
        return aes_key_wrap(kek, dek)

    def unwrap_key(self, wrapped_dek: bytes, key_id: str) -> bytes:
        """Unwraps a 256-bit Data Encryption Key (DEK) using AES Key Wrap (RFC 3394)."""
        kek = self.get_key(key_id)
        try:
            return aes_key_unwrap(kek, wrapped_dek)
        except InvalidUnwrap as e:
            raise ValueError(
                f"Failed to unwrap DEK with key_id '{key_id}': integrity check failed."
            ) from e

    def derive_purpose_key(self, purpose: str, key_id: str | None = None) -> bytes:
        """Derives a 256-bit purpose-specific subkey using HKDF-SHA256."""
        target_id = key_id or self.current_key_id()
        master = self.get_key(target_id)
        kdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=f"FreqID-{purpose}-v1".encode("ascii"),
        )
        return kdf.derive(master)

    def get_payload_keypair(
        self, key_id: str | None = None
    ) -> tuple[x25519.X25519PrivateKey, bytes]:
        """Derives the server's static X25519 payload private and public keys."""
        target_id = key_id or self.current_key_id()
        payload_seed = self.derive_purpose_key("payload", target_id)
        priv = x25519.X25519PrivateKey.from_private_bytes(payload_seed)
        pub_bytes = priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return priv, pub_bytes

    def get_key_hierarchy(self, key_id: str | None = None) -> KeyHierarchy:
        """Constructs the full derived subkey hierarchy for the given master key."""
        target_id = key_id or self.current_key_id()
        priv, pub_bytes = self.get_payload_keypair(target_id)
        return KeyHierarchy(
            master_key_id=target_id,
            template_key=self.derive_purpose_key("template", target_id),
            transform_key=self.derive_purpose_key("transform", target_id),
            audit_key=self.derive_purpose_key("audit", target_id),
            token_key=self.derive_purpose_key("token", target_id),
            payload_private_key=priv,
            payload_public_key_bytes=pub_bytes,
        )


class EnvOrFileKeyProvider(KeyProvider):
    """
    Loads 256-bit AES master keys from environment variables or POSIX 0600 secret files.
    Refuses to start if permissions are insecure, or if keys are missing or malformed.
    """

    def __init__(
        self,
        default_key: bytes | None = None,
        default_key_id: str = "key_v1",
        key_file_path: str | None = None,
        key_env_var: str = "FREQID_MASTER_KEY",
        secondary_keys: dict[str, bytes] | None = None,
    ) -> None:
        self._keys: dict[str, bytes] = {}
        self._active_key_id = default_key_id

        # 1. Programmatic default key
        if default_key is not None:
            self._validate_key(default_key)
            self._keys[default_key_id] = default_key

        # 2. File source
        effective_path = key_file_path or os.environ.get("FREQID_MASTER_KEY_FILE")
        if effective_path:
            self._load_from_file(effective_path, default_key_id)

        # 3. Environment variable source
        if not self._keys and key_env_var in os.environ:
            raw_val = os.environ[key_env_var].strip()
            key_bytes = self._decode_key_str(raw_val)
            self._validate_key(key_bytes)
            self._keys[default_key_id] = key_bytes

        # 4. Secondary / historical keys for key rotation
        if secondary_keys:
            for k_id, k_val in secondary_keys.items():
                self._validate_key(k_val)
                self._keys[k_id] = k_val

        # Support FREQID_KEY_<id> environment variables
        for env_name, env_val in os.environ.items():
            if env_name.startswith("FREQID_KEY_"):
                k_id = env_name[len("FREQID_KEY_") :].lower()
                k_bytes = self._decode_key_str(env_val.strip())
                self._validate_key(k_bytes)
                self._keys[k_id] = k_bytes

        active_override = os.environ.get("FREQID_ACTIVE_KEY_ID")
        if active_override:
            self._active_key_id = active_override

        if not self._keys:
            raise ValueError(
                "No master encryption key provided. Set FREQID_MASTER_KEY or FREQID_MASTER_KEY_FILE."
            )

        if self._active_key_id not in self._keys:
            raise ValueError(
                f"Active key id '{self._active_key_id}' is not among loaded master keys: {list(self._keys.keys())}"
            )

    def _decode_key_str(self, val: str) -> bytes:
        try:
            return base64.b64decode(val)
        except Exception as e:
            raise ValueError("Master key string is not valid base64.") from e

    def _validate_key(self, key_bytes: bytes) -> None:
        if len(key_bytes) != 32:
            raise ValueError(
                f"Master encryption key must be exactly 32 bytes (256 bits), got {len(key_bytes)} bytes."
            )

    def _load_from_file(self, file_path: str, key_id: str) -> None:
        p = Path(file_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Master key file not found: {file_path}")

        # Strict POSIX permission audit: reject if group- or world-accessible
        file_mode = p.stat().st_mode
        if file_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise PermissionError(
                f"Insecure permissions on master key file {file_path} (mode {oct(file_mode)}). "
                f"File must be readable only by owner (e.g. chmod 0600 or 0400)."
            )

        content = p.read_text(encoding="utf-8").strip()
        key_bytes = self._decode_key_str(content)
        self._validate_key(key_bytes)
        self._keys[key_id] = key_bytes

    def get_key(self, key_id: str) -> bytes:
        if key_id not in self._keys:
            raise KeyError(
                f"Master key with id '{key_id}' not found. Available keys: {list(self._keys.keys())}"
            )
        return self._keys[key_id]

    def current_key_id(self) -> str:
        return self._active_key_id

    def set_active_key(self, key_id: str, key_bytes: bytes) -> None:
        """Dynamically registers and sets a new active key for rotation testing."""
        self._validate_key(key_bytes)
        self._keys[key_id] = key_bytes
        self._active_key_id = key_id
