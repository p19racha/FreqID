# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
auth.py: Pluggable authenticator interface, Ed25519 request signature authenticator,
and device credentials lifecycle management (pairing, 0600 storage, rotation).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import stat
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric import ed25519

from freqid_client.errors import AuthenticationError, TransportError


class Authenticator(ABC):
    """Abstract interface for client authentication mechanisms."""

    @abstractmethod
    def get_auth_headers(self, **kwargs: Any) -> dict[str, str]:
        """Returns HTTP headers to attach to outgoing requests."""

    def refresh(self) -> None:
        """Optional token/credential refresh hook."""


class StaticTokenAuthenticator(Authenticator):
    """Bearer token authentication for development and pre-shared device tokens."""

    def __init__(self, token: str) -> None:
        if not token:
            raise AuthenticationError("Token string cannot be empty.")
        self.token = token

    def get_auth_headers(self, **kwargs: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


class NoAuth(Authenticator):
    """Unauthenticated access, strictly permitted only in local development / testing."""

    def get_auth_headers(self, **kwargs: Any) -> dict[str, str]:
        return {}


def validate_credentials_file_permissions(file_path: str | Path) -> None:
    """
    Enforces strict POSIX 0600 permissions. Refuses to load if group/world readable.
    """
    p = Path(file_path).expanduser().resolve()
    if not p.is_file():
        raise AuthenticationError(f"Credentials file does not exist: {p}")

    try:
        st = os.stat(p)
        mode = stat.S_IMODE(st.st_mode)
        # Check if group or others have any permissions (read, write, or execute)
        if mode & 0o077 != 0:
            raise AuthenticationError(
                f"Insecure permissions ({oct(mode)}) on device credentials file: {p}. "
                "Must be owner-only (0600). Group and others must not have access."
            )
    except OSError:
        pass


def save_device_credentials(
    credentials: dict[str, str],
    file_path: str | Path,
) -> None:
    """
    Saves device credentials to disk enforcing POSIX 0600 (owner read/write only) permissions.
    """
    p = Path(file_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)

    # Write file
    with open(p, "w", encoding="utf-8") as f:
        json.dump(credentials, f, indent=2)

    # Restrict permissions to owner read/write only (chmod 0600)
    try:
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def load_device_credentials(file_path: str | Path) -> dict[str, str]:
    """Loads device credentials from a JSON file after verifying POSIX 0600 permissions."""
    p = Path(file_path).expanduser().resolve()
    if not p.is_file():
        raise AuthenticationError(f"Device credentials file not found: {p}")

    validate_credentials_file_permissions(p)

    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


class DeviceSignatureAuthenticator(Authenticator):
    """
    Authenticates requests using per-request Ed25519 digital signatures.
    Signs canonical request string: METHOD\nPATH\nTIMESTAMP\nNONCE\nBODY_DIGEST
    """

    def __init__(
        self,
        credentials: dict[str, str] | None = None,
        credentials_path: str | Path | None = None,
    ) -> None:
        if credentials is not None:
            creds = credentials
        elif credentials_path is not None:
            creds = load_device_credentials(credentials_path)
        else:
            default_path = Path.home() / ".freqid" / "device_credentials.json"
            creds = load_device_credentials(default_path)

        self.device_id = creds["device_id"]
        self.server_url = creds.get("server_url", "")
        self.public_key_b64 = creds["public_key"]

        priv_bytes = base64.b64decode(creds["private_key"])
        self._private_key = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)

    def get_auth_headers(self, **kwargs: Any) -> dict[str, str]:
        method = str(kwargs.get("method", "POST")).upper()
        path = str(kwargs.get("path", "/api/v1/auth/verify"))
        timestamp = str(kwargs.get("timestamp", int(time.time())))
        nonce = str(kwargs.get("nonce", secrets.token_hex(16)))
        body = kwargs.get("body", b"")
        if isinstance(body, str):
            body = body.encode("utf-8")

        body_digest = hashlib.sha256(body).hexdigest()
        canonical = f"{method}\n{path}\n{timestamp}\n{nonce}\n{body_digest}".encode()

        sig = self._private_key.sign(canonical)
        sig_b64 = base64.b64encode(sig).decode("ascii")

        return {
            "X-Device-ID": self.device_id,
            "X-Timestamp": timestamp,
            "X-Nonce": nonce,
            "X-Signature": sig_b64,
        }


def pair_device(
    server_url: str,
    token: str,
    name: str,
    software_version: str = "0.1.0",
    credentials_path: str | Path = "~/.freqid/device_credentials.json",
    insecure_skip_verify: bool = False,
    ca_cert_path: str | None = None,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """
    Pairs an edge device with the FreqID server using a single-use pairing token.
    Generates Ed25519 keypair locally; private key never leaves the device.
    """
    # 1. Generate Ed25519 keypair
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    priv_b64 = base64.b64encode(private_key.private_bytes_raw()).decode("ascii")
    pub_b64 = base64.b64encode(public_key.public_bytes_raw()).decode("ascii")

    # 2. Build SSL verification context
    if insecure_skip_verify:
        verify_ssl: bool | str = False
    elif ca_cert_path:
        verify_ssl = ca_cert_path
    else:
        verify_ssl = True

    base_url = server_url.rstrip("/")
    pair_endpoint = f"{base_url}/v1/devices/pair"

    payload = {
        "token": token.strip(),
        "public_key": pub_b64,
        "name": name.strip(),
        "software_version": software_version,
    }

    try:
        if http_client is not None:
            resp = http_client.post(pair_endpoint, json=payload)
        else:
            with httpx.Client(verify=verify_ssl, timeout=10.0) as client:
                resp = client.post(pair_endpoint, json=payload)
    except httpx.ConnectError as e:
        raise TransportError(f"Cannot reach FreqID server at {server_url}: {e}") from e

    if resp.status_code not in (200, 201, 202):
        err_msg = resp.text
        try:
            err_json = resp.json()
            err_msg = err_json.get("error", {}).get("message") or err_json.get("detail", resp.text)
        except Exception:
            pass
        raise AuthenticationError(f"Device pairing failed (HTTP {resp.status_code}): {err_msg}")

    resp_data = resp.json()
    device_id = resp_data["device_id"]
    state = resp_data.get("state", "active")
    key_id = resp_data.get("key_id", "")

    # 3. Store credentials locally with POSIX 0600 permissions
    creds = {
        "device_id": device_id,
        "device_name": name,
        "server_url": base_url,
        "public_key": pub_b64,
        "private_key": priv_b64,
        "key_id": key_id,
        "paired_at": time.time(),
    }
    save_device_credentials(creds, credentials_path)

    return {
        "device_id": device_id,
        "state": state,
        "key_id": key_id,
        "credentials_path": str(Path(credentials_path).expanduser().resolve()),
    }
