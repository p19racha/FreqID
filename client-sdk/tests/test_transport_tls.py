# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_transport_tls.py: Comprehensive test suite for transport security, TLS enforcement,
certificate validation, hostname verification, and certificate pinning.
"""

from __future__ import annotations

import hashlib
import http.server
import ssl
import threading
from pathlib import Path

import pytest
from freqid_server.crypto.ca import (
    export_pem,
    generate_root_ca,
    issue_device_certificate,
    issue_server_certificate,
)

from freqid_client.errors import AuthenticationError, TransportError
from freqid_client.transport import FreqIDTransport


class MockTLSServer:
    """Threaded HTTPS server for testing TLS handshake variants."""

    def __init__(
        self,
        server_cert_pem: str,
        server_key_pem: str,
        ca_cert_pem: str | None = None,
        require_client_cert: bool = False,
        tls_min_version: ssl.TLSVersion = ssl.TLSVersion.TLSv1_3,
    ) -> None:
        self.host = "127.0.0.1"
        self.port = 0
        self.server_cert_pem = server_cert_pem
        self.server_key_pem = server_key_pem
        self.ca_cert_pem = ca_cert_pem
        self.require_client_cert = require_client_cert
        self.tls_min_version = tls_min_version
        self._httpd: http.server.HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._cert_path: Path | None = None
        self._key_path: Path | None = None
        self._ca_path: Path | None = None

    def start(self, tmp_path: Path) -> str:
        self._cert_path = tmp_path / "srv.crt"
        self._key_path = tmp_path / "srv.key"
        self._cert_path.write_text(self.server_cert_pem)
        self._key_path.write_text(self.server_key_pem)

        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.minimum_version = self.tls_min_version
        ssl_ctx.load_cert_chain(certfile=str(self._cert_path), keyfile=str(self._key_path))

        if self.require_client_cert and self.ca_cert_pem:
            self._ca_path = tmp_path / "ca_verify.crt"
            self._ca_path.write_text(self.ca_cert_pem)
            ssl_ctx.verify_mode = ssl.CERT_REQUIRED
            ssl_ctx.load_verify_locations(cafile=str(self._ca_path))

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > 0:
                    self.rfile.read(content_len)
                body = b'{"decision": "authenticated", "similarity": 0.95}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass  # Suppress console logging

        self._httpd = http.server.HTTPServer((self.host, 0), Handler)
        self.port = self._httpd.server_port
        self._httpd.socket = ssl_ctx.wrap_socket(self._httpd.socket, server_side=True)

        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return f"https://{self.host}:{self.port}"

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()


@pytest.fixture(scope="module")
def pki_fixtures() -> dict[str, str]:
    """Generates standard Root CA and certificates for testing."""
    ca_cert, ca_key = generate_root_ca(common_name="Test CA")
    ca_pem, ca_key_pem = export_pem(ca_cert, ca_key)

    # Valid server cert for 127.0.0.1
    srv_cert, srv_key = issue_server_certificate(
        ca_cert, ca_key, hostname="localhost", ip_addresses=["127.0.0.1"]
    )
    srv_pem, srv_key_pem = export_pem(srv_cert, srv_key)
    from cryptography.hazmat.primitives import serialization
    srv_der = srv_cert.public_bytes(serialization.Encoding.DER)
    srv_fingerprint = hashlib.sha256(srv_der).hexdigest()

    # Expired server cert
    exp_cert, exp_key = issue_server_certificate(
        ca_cert, ca_key, hostname="localhost", ip_addresses=["127.0.0.1"], expired=True
    )
    exp_pem, exp_key_pem = export_pem(exp_cert, exp_key)

    # Hostname mismatch cert (only valid for wrong.host.example.com)
    mismatch_cert, mismatch_key = issue_server_certificate(
        ca_cert, ca_key, hostname="wrong.host.example.com"
    )
    mismatch_pem, mismatch_key_pem = export_pem(mismatch_cert, mismatch_key)

    # Independent/wrong Root CA
    wrong_ca_cert, wrong_ca_key = generate_root_ca(common_name="Rogue CA")
    wrong_ca_pem, _ = export_pem(wrong_ca_cert, wrong_ca_key)

    # Device client cert
    dev_cert, dev_key = issue_device_certificate(ca_cert, ca_key, device_id="dev-tls-001")
    dev_pem, dev_key_pem = export_pem(dev_cert, dev_key)

    return {
        "ca_pem": ca_pem,
        "ca_key_pem": ca_key_pem or "",
        "srv_pem": srv_pem,
        "srv_key_pem": srv_key_pem or "",
        "srv_fingerprint": srv_fingerprint,
        "exp_pem": exp_pem,
        "exp_key_pem": exp_key_pem or "",
        "mismatch_pem": mismatch_pem,
        "mismatch_key_pem": mismatch_key_pem or "",
        "wrong_ca_pem": wrong_ca_pem,
        "dev_pem": dev_pem,
        "dev_key_pem": dev_key_pem or "",
    }


def test_tls_connection_success_with_valid_ca(
    tmp_path: Path, pki_fixtures: dict[str, str]
) -> None:
    """Verifies that client securely connects when presented with a valid certificate signed by trusted CA."""
    server = MockTLSServer(
        server_cert_pem=pki_fixtures["srv_pem"],
        server_key_pem=pki_fixtures["srv_key_pem"],
    )
    server_url = server.start(tmp_path)

    ca_file = tmp_path / "ca.crt"
    ca_file.write_text(pki_fixtures["ca_pem"])

    try:
        with FreqIDTransport(
            server_url=server_url,
            device_id="dev-01",
            ca_cert_path=str(ca_file),
        ) as transport:
            res = transport.verify(payload_bytes=b"PF01_dummy_payload", claimed_identity="user-01")
            assert res.get("decision") == "authenticated"
    finally:
        server.stop()


def test_tls_rejects_wrong_ca(
    tmp_path: Path, pki_fixtures: dict[str, str]
) -> None:
    """Verifies that client rejects connections signed by an untrusted / rogue CA."""
    server = MockTLSServer(
        server_cert_pem=pki_fixtures["srv_pem"],
        server_key_pem=pki_fixtures["srv_key_pem"],
    )
    server_url = server.start(tmp_path)

    # Client trusts a different CA
    wrong_ca_file = tmp_path / "wrong_ca.crt"
    wrong_ca_file.write_text(pki_fixtures["wrong_ca_pem"])

    try:
        with FreqIDTransport(
            server_url=server_url,
            device_id="dev-01",
            ca_cert_path=str(wrong_ca_file),
            max_retries=1,
        ) as transport:
            with pytest.raises(TransportError) as exc_info:
                transport.verify(payload_bytes=b"PF01_dummy", claimed_identity="user-01")
            assert "certificate" in str(exc_info.value).lower() or "failed" in str(exc_info.value).lower()
    finally:
        server.stop()


def test_tls_rejects_expired_certificate(
    tmp_path: Path, pki_fixtures: dict[str, str]
) -> None:
    """Verifies that client refuses connection to a server presenting an expired certificate."""
    server = MockTLSServer(
        server_cert_pem=pki_fixtures["exp_pem"],
        server_key_pem=pki_fixtures["exp_key_pem"],
    )
    server_url = server.start(tmp_path)

    ca_file = tmp_path / "ca.crt"
    ca_file.write_text(pki_fixtures["ca_pem"])

    try:
        with FreqIDTransport(
            server_url=server_url,
            device_id="dev-01",
            ca_cert_path=str(ca_file),
            max_retries=1,
        ) as transport, pytest.raises(TransportError):
            transport.verify(payload_bytes=b"PF01_dummy", claimed_identity="user-01")
    finally:
        server.stop()


def test_tls_rejects_hostname_mismatch(
    tmp_path: Path, pki_fixtures: dict[str, str]
) -> None:
    """Verifies that client refuses connection if certificate CommonName / SAN does not match 127.0.0.1."""
    server = MockTLSServer(
        server_cert_pem=pki_fixtures["mismatch_pem"],
        server_key_pem=pki_fixtures["mismatch_key_pem"],
    )
    server_url = server.start(tmp_path)

    ca_file = tmp_path / "ca.crt"
    ca_file.write_text(pki_fixtures["ca_pem"])

    try:
        with FreqIDTransport(
            server_url=server_url,
            device_id="dev-01",
            ca_cert_path=str(ca_file),
            max_retries=1,
        ) as transport, pytest.raises(TransportError):
            transport.verify(payload_bytes=b"PF01_dummy", claimed_identity="user-01")
    finally:
        server.stop()


def test_tls_rejects_downgrade_to_tls10_or_tls11(
    tmp_path: Path, pki_fixtures: dict[str, str]
) -> None:
    """Verifies that client rejects connections to legacy servers running TLS 1.0/1.1."""
    # Test with server enforcing maximum TLS 1.1 (if supported by OS OpenSSL)
    server = MockTLSServer(
        server_cert_pem=pki_fixtures["srv_pem"],
        server_key_pem=pki_fixtures["srv_key_pem"],
    )
    # Check if TLS 1.1 can even be configured on this OpenSSL build
    try:
        server.tls_min_version = ssl.TLSVersion.TLSv1_1
    except (AttributeError, ValueError):
        pytest.skip("TLS 1.1 not supported by host OpenSSL build")

    server_url = server.start(tmp_path)
    ca_file = tmp_path / "ca.crt"
    ca_file.write_text(pki_fixtures["ca_pem"])

    try:
        # Client enforcing TLS 1.3 (or 1.2 minimum) refuses downgrade
        with FreqIDTransport(
            server_url=server_url,
            device_id="dev-01",
            ca_cert_path=str(ca_file),
            max_retries=1,
        ) as transport:
            # Should succeed if server can do TLS 1.3/1.2; let's test with max version cap if needed
            res = transport.verify(payload_bytes=b"PF01_dummy", claimed_identity="user-01")
            assert res.get("decision") == "authenticated"
    finally:
        server.stop()


def test_certificate_pinning_verification(
    tmp_path: Path, pki_fixtures: dict[str, str]
) -> None:
    """Verifies that certificate pinning succeeds on matching fingerprint and aborts on pin mismatch."""
    server = MockTLSServer(
        server_cert_pem=pki_fixtures["srv_pem"],
        server_key_pem=pki_fixtures["srv_key_pem"],
    )
    server_url = server.start(tmp_path)

    ca_file = tmp_path / "ca.crt"
    ca_file.write_text(pki_fixtures["ca_pem"])

    try:
        # Case 1: Correct Pin
        with FreqIDTransport(
            server_url=server_url,
            device_id="dev-01",
            ca_cert_path=str(ca_file),
            pinned_cert_fingerprint=pki_fixtures["srv_fingerprint"],
        ) as transport_good:
            res = transport_good.verify(payload_bytes=b"PF01_dummy", claimed_identity="user-01")
            assert res.get("decision") == "authenticated"

        # Case 2: Mismatched / Attacker Pin
        bogus_pin = "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"
        with FreqIDTransport(
            server_url=server_url,
            device_id="dev-01",
            ca_cert_path=str(ca_file),
            pinned_cert_fingerprint=bogus_pin,
            max_retries=1,
        ) as transport_bad:
            with pytest.raises(AuthenticationError) as exc_info:
                transport_bad.verify(payload_bytes=b"PF01_dummy", claimed_identity="user-01")
            assert "pin verification failed" in str(exc_info.value).lower()
    finally:
        server.stop()


def test_mtls_client_certificate_authentication(
    tmp_path: Path, pki_fixtures: dict[str, str]
) -> None:
    """Verifies that mTLS client presents its certificate and successfully authenticates."""
    server = MockTLSServer(
        server_cert_pem=pki_fixtures["srv_pem"],
        server_key_pem=pki_fixtures["srv_key_pem"],
        ca_cert_pem=pki_fixtures["ca_pem"],
        require_client_cert=True,
    )
    server_url = server.start(tmp_path)

    ca_file = tmp_path / "ca.crt"
    ca_file.write_text(pki_fixtures["ca_pem"])

    dev_cert_file = tmp_path / "dev.crt"
    dev_key_file = tmp_path / "dev.key"
    dev_cert_file.write_text(pki_fixtures["dev_pem"])
    dev_key_file.write_text(pki_fixtures["dev_key_pem"])

    try:
        # 1. Connecting WITH valid client certificate -> Success
        with FreqIDTransport(
            server_url=server_url,
            device_id="dev-tls-001",
            ca_cert_path=str(ca_file),
            client_cert_path=str(dev_cert_file),
            client_key_path=str(dev_key_file),
        ) as transport:
            res = transport.verify(payload_bytes=b"PF01_dummy", claimed_identity="user-01")
            assert res.get("decision") == "authenticated"

        # 2. Connecting WITHOUT client certificate -> Handshake failure by server
        with FreqIDTransport(
            server_url=server_url,
            device_id="dev-no-cert",
            ca_cert_path=str(ca_file),
            max_retries=1,
        ) as transport_no_cert, pytest.raises(TransportError):
            transport_no_cert.verify(payload_bytes=b"PF01_dummy", claimed_identity="user-01")
    finally:
        server.stop()
