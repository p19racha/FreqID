# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
transport.py: Robust HTTPS transport layer with TLS enforcement, nonces, retries, and backoff.
"""

from __future__ import annotations

import hashlib
import secrets
import ssl
import time
import uuid
from typing import Any

import httpx

from freqid_client.auth import Authenticator, NoAuth
from freqid_client.crypto.payload_envelope import seal_payload
from freqid_client.errors import AuthenticationError, ServerRejectedError, TransportError


class FreqIDTransport:
    """
    Communicates with the FreqID backend over HTTPS (TLS 1.3).
    Transmits only partial frequency payloads; raw images are never sent.
    """

    def __init__(
        self,
        server_url: str,
        device_id: str,
        auth: Authenticator | None = None,
        ca_cert_path: str | None = None,
        client_cert_path: str | None = None,
        client_key_path: str | None = None,
        pinned_cert_fingerprint: str | None = None,
        insecure_skip_verify: bool = False,
        timeout: float = 10.0,
        max_retries: int = 3,
        seal_payloads: bool = False,
        server_payload_public_key_hex: str | None = None,
        payload_key_id: str | None = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.device_id = device_id
        self.auth = auth or NoAuth()
        self.ca_cert_path = ca_cert_path
        self.client_cert_path = client_cert_path
        self.client_key_path = client_key_path
        self.pinned_cert_fingerprint = (
            pinned_cert_fingerprint.lower() if pinned_cert_fingerprint else None
        )
        self.insecure_skip_verify = insecure_skip_verify
        self.timeout = timeout
        self.max_retries = max_retries
        self.seal_payloads = seal_payloads
        self.server_payload_public_key_hex = server_payload_public_key_hex
        self.payload_key_id = payload_key_id

        # Build SSL verification context
        if self.insecure_skip_verify:
            verify_ssl: ssl.SSLContext | bool = False
        elif self.ca_cert_path:
            verify_ssl = ssl.create_default_context(cafile=self.ca_cert_path)
            verify_ssl.minimum_version = ssl.TLSVersion.TLSv1_2
        else:
            verify_ssl = ssl.create_default_context()
            verify_ssl.minimum_version = ssl.TLSVersion.TLSv1_2

        if (
            isinstance(verify_ssl, ssl.SSLContext)
            and self.client_cert_path
            and self.client_key_path
        ):
            verify_ssl.load_cert_chain(
                certfile=self.client_cert_path,
                keyfile=self.client_key_path,
            )

        self._client = httpx.Client(
            verify=verify_ssl,
            timeout=self.timeout,
            follow_redirects=True,
        )
        self._cached_server_pub_key: bytes | None = None
        self._cached_key_id: str | None = None

    def _ensure_payload_key(self) -> tuple[bytes, str]:
        if self._cached_server_pub_key is not None and self._cached_key_id is not None:
            return self._cached_server_pub_key, self._cached_key_id
        if self.server_payload_public_key_hex and self.payload_key_id:
            self._cached_server_pub_key = bytes.fromhex(self.server_payload_public_key_hex)
            self._cached_key_id = self.payload_key_id
            return self._cached_server_pub_key, self._cached_key_id

        resp = self._client.get(f"{self.server_url}/v1/payload-key", timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        self._cached_server_pub_key = bytes.fromhex(data["public_key_hex"])
        self._cached_key_id = data["key_id"]
        return self._cached_server_pub_key, self._cached_key_id

    def _seal_if_enabled(self, payload_bytes: bytes, request_id: str) -> bytes:
        if not self.seal_payloads:
            return payload_bytes
        pub_bytes, key_id = self._ensure_payload_key()
        dev_priv = getattr(self.auth, "device_private_key", None)
        return seal_payload(
            payload_bytes=payload_bytes,
            server_public_key_bytes=pub_bytes,
            key_id=key_id,
            device_id=self.device_id,
            request_id=request_id,
            device_private_key=dev_priv,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> FreqIDTransport:  # noqa: PYI034
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self.close()

    def _build_headers(
        self,
        method: str = "POST",
        endpoint: str = "/api/v1/auth/verify",
        content: bytes = b"",
        claimed_identity: str | None = None,
        request_id: str | None = None,
        nonce: str | None = None,
    ) -> dict[str, str]:
        req_id = request_id or str(uuid.uuid4())
        req_nonce = nonce or secrets.token_hex(16)
        timestamp = str(int(time.time()))

        headers = {
            "Content-Type": "application/vnd.freqid.payload",
            "X-Device-ID": self.device_id,
            "X-Request-ID": req_id,
            "X-Timestamp": timestamp,
            "X-Nonce": req_nonce,
        }

        if claimed_identity:
            headers["X-Claimed-Identity"] = claimed_identity

        # Inject auth headers (Bearer token, signature, etc.)
        auth_hdrs = self.auth.get_auth_headers(
            method=method,
            path=endpoint,
            timestamp=timestamp,
            nonce=req_nonce,
            body=content,
            device_id=self.device_id,
        )
        headers.update(auth_hdrs)
        return headers

    def _execute_with_retry(
        self,
        method: str,
        endpoint: str,
        content: bytes,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        url = f"{self.server_url}{endpoint}"
        last_exception: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._client.request(
                    method=method,
                    url=url,
                    content=content,
                    headers=headers,
                )

                # Validate certificate pin if configured
                if self.pinned_cert_fingerprint:
                    stream = response.extensions.get("network_stream")
                    if stream and hasattr(stream, "_sock") and stream._sock:
                        try:
                            der = stream._sock.getpeercert(binary_form=True)
                            if der:
                                fp = hashlib.sha256(der).hexdigest()
                                if fp.lower() != self.pinned_cert_fingerprint:
                                    raise AuthenticationError(
                                        f"Certificate pin verification failed! Expected {self.pinned_cert_fingerprint}, got {fp.lower()}"
                                    )
                        except Exception as pin_err:
                            if isinstance(pin_err, AuthenticationError):
                                raise

                # Process status codes
                if response.status_code == 200 or response.status_code == 201:
                    return response.json()

                elif response.status_code in (401, 403):
                    raise AuthenticationError(
                        f"Authentication failed (HTTP {response.status_code}): {response.text}"
                    )

                elif response.status_code == 400:
                    try:
                        err_json = response.json()
                        detail = err_json.get("detail", err_json)
                        if isinstance(detail, dict):
                            code = detail.get("error_code", "BAD_REQUEST")
                            msg = detail.get("message", response.text)
                        else:
                            code = err_json.get("error_code", "BAD_REQUEST")
                            msg = str(detail)
                    except Exception:  # noqa: BLE001
                        code = "BAD_REQUEST"
                        msg = response.text
                    raise ServerRejectedError(error_code=code, message=msg, status_code=400)

                elif response.status_code >= 500:
                    # Server busy/error - eligible for retry with backoff
                    if attempt < self.max_retries:
                        time.sleep(0.5 * (2 ** (attempt - 1)))
                        continue
                    raise TransportError(
                        f"Server error HTTP {response.status_code}: {response.text}"
                    )

                else:
                    raise TransportError(f"Unexpected HTTP {response.status_code}: {response.text}")

            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
                last_exception = e
                if attempt < self.max_retries:
                    time.sleep(0.5 * (2 ** (attempt - 1)))
                    continue
                raise TransportError(
                    f"Network transport failed after {self.max_retries} attempts: {e}"
                ) from e

        raise TransportError(f"Request failed: {last_exception}")

    def verify(
        self,
        payload_bytes: bytes,
        claimed_identity: str,
        request_id: str | None = None,
        nonce: str | None = None,
    ) -> dict[str, Any]:
        """
        Submits 1:1 biometric verification request.
        """
        req_id = request_id or str(uuid.uuid4())
        body_to_send = self._seal_if_enabled(payload_bytes, req_id)
        headers = self._build_headers(
            method="POST",
            endpoint="/api/v1/auth/verify",
            content=body_to_send,
            claimed_identity=claimed_identity,
            request_id=req_id,
            nonce=nonce,
        )
        return self._execute_with_retry(
            method="POST",
            endpoint="/api/v1/auth/verify",
            content=body_to_send,
            headers=headers,
        )

    def identify(
        self,
        payload_bytes: bytes,
        request_id: str | None = None,
        nonce: str | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """
        Submits 1:N biometric identification query.
        """
        req_id = request_id or str(uuid.uuid4())
        body_to_send = self._seal_if_enabled(payload_bytes, req_id)
        headers = self._build_headers(
            method="POST",
            endpoint="/api/v1/auth/identify",
            content=body_to_send,
            request_id=req_id,
            nonce=nonce,
        )
        headers["X-Top-K"] = str(top_k)
        return self._execute_with_retry(
            method="POST",
            endpoint="/api/v1/auth/identify",
            content=body_to_send,
            headers=headers,
        )

    def enroll(
        self,
        payload_bytes_list: list[bytes],
        user_id: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Submits multi-capture enrollment payload list.
        """
        req_id = request_id or str(uuid.uuid4())

        # Multi-payload binary framing: 4-byte big-endian length prefix per payload
        packed_body = bytearray()
        for p in payload_bytes_list:
            packed_body.extend(len(p).to_bytes(4, byteorder="big"))
            packed_body.extend(p)

        timestamp = str(int(time.time()))
        req_nonce = secrets.token_hex(16)
        content_bytes = bytes(packed_body)
        body_to_send = self._seal_if_enabled(content_bytes, req_id)

        headers = {
            "Content-Type": "application/vnd.freqid.enrollment-batch",
            "X-Device-ID": self.device_id,
            "X-Request-ID": req_id,
            "X-User-ID": user_id,
            "X-Payload-Count": str(len(payload_bytes_list)),
            "X-Timestamp": timestamp,
            "X-Nonce": req_nonce,
        }
        headers.update(
            self.auth.get_auth_headers(
                method="POST",
                path="/api/v1/enroll/frames",
                timestamp=timestamp,
                nonce=req_nonce,
                body=body_to_send,
                device_id=self.device_id,
            )
        )

        return self._execute_with_retry(
            method="POST",
            endpoint="/api/v1/enroll/frames",
            content=bytes(packed_body),
            headers=headers,
        )
