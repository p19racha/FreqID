# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
transport.py: Robust HTTPS transport layer with TLS enforcement, nonces, retries, and backoff.
"""

from __future__ import annotations

import datetime
import secrets
import time
import uuid
from typing import Any

import httpx

from freqid_client.auth import Authenticator, NoAuth
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
        insecure_skip_verify: bool = False,
        timeout: float = 10.0,
        max_retries: int = 3,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.device_id = device_id
        self.auth = auth or NoAuth()
        self.ca_cert_path = ca_cert_path
        self.insecure_skip_verify = insecure_skip_verify
        self.timeout = timeout
        self.max_retries = max_retries

        # Build SSL verification context
        if self.insecure_skip_verify:
            verify_ssl: bool | str = False
        elif self.ca_cert_path:
            verify_ssl = self.ca_cert_path
        else:
            verify_ssl = True

        self._client = httpx.Client(
            verify=verify_ssl,
            timeout=self.timeout,
            follow_redirects=True,
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
        claimed_identity: str | None = None,
        request_id: str | None = None,
        nonce: str | None = None,
    ) -> dict[str, str]:
        req_id = request_id or str(uuid.uuid4())
        req_nonce = nonce or secrets.token_hex(16)
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        headers = {
            "Content-Type": "application/vnd.freqid.payload",
            "X-Device-ID": self.device_id,
            "X-Request-ID": req_id,
            "X-Timestamp": timestamp,
            "X-Nonce": req_nonce,
        }

        if claimed_identity:
            headers["X-Claimed-Identity"] = claimed_identity

        # Inject auth headers (Bearer token, etc.)
        headers.update(self.auth.get_auth_headers())
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
                    raise TransportError(f"Server error HTTP {response.status_code}: {response.text}")

                else:
                    raise TransportError(f"Unexpected HTTP {response.status_code}: {response.text}")

            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
                last_exception = e
                if attempt < self.max_retries:
                    time.sleep(0.5 * (2 ** (attempt - 1)))
                    continue
                raise TransportError(f"Network transport failed after {self.max_retries} attempts: {e}") from e

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
        headers = self._build_headers(
            claimed_identity=claimed_identity,
            request_id=request_id,
            nonce=nonce,
        )
        return self._execute_with_retry(
            method="POST",
            endpoint="/api/v1/auth/verify",
            content=payload_bytes,
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
        headers = self._build_headers(
            request_id=request_id,
            nonce=nonce,
        )
        headers["X-Top-K"] = str(top_k)
        return self._execute_with_retry(
            method="POST",
            endpoint="/api/v1/auth/identify",
            content=payload_bytes,
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

        headers = {
            "Content-Type": "application/vnd.freqid.enrollment-batch",
            "X-Device-ID": self.device_id,
            "X-Request-ID": req_id,
            "X-User-ID": user_id,
            "X-Payload-Count": str(len(payload_bytes_list)),
        }
        headers.update(self.auth.get_auth_headers())

        return self._execute_with_retry(
            method="POST",
            endpoint="/api/v1/enroll/frames",
            content=bytes(packed_body),
            headers=headers,
        )
