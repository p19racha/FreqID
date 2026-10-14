# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
auth.py: Pluggable authenticator interface and device credentials management.
"""

from __future__ import annotations

import json
import os
import stat
from abc import ABC, abstractmethod
from pathlib import Path

from freqid_client.errors import AuthenticationError


class Authenticator(ABC):
    """Abstract interface for client authentication mechanisms."""

    @abstractmethod
    def get_auth_headers(self) -> dict[str, str]:
        """Returns HTTP headers to attach to outgoing requests."""

    def refresh(self) -> None:
        """Optional token/credential refresh hook."""


class StaticTokenAuthenticator(Authenticator):
    """Bearer token authentication for development and pre-shared device tokens."""

    def __init__(self, token: str) -> None:
        if not token:
            raise AuthenticationError("Token string cannot be empty.")
        self.token = token

    def get_auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


class NoAuth(Authenticator):
    """Unauthenticated access, strictly permitted only in local development / testing."""

    def get_auth_headers(self) -> dict[str, str]:
        return {}


def save_device_credentials(
    credentials: dict[str, str],
    file_path: str | Path,
) -> None:
    """
    Saves device credentials to disk enforcing POSIX 0600 (owner read/write only) permissions.
    """
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    # Write file
    with open(p, "w", encoding="utf-8") as f:
        json.dump(credentials, f, indent=2)

    # Restrict permissions to owner read/write only (chmod 0600)
    try:
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # On non-POSIX filesystems (e.g. FAT), chmod might be a no-op


def load_device_credentials(file_path: str | Path) -> dict[str, str]:
    """Loads device credentials from a JSON file."""
    p = Path(file_path)
    if not p.is_file():
        raise AuthenticationError(f"Device credentials file not found: {file_path}")

    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)
