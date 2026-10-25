# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
ca.py: Internal Certificate Authority and edge device X.509 certificate provisioning.
Uses standard cryptography.x509 primitives with ECDSA P-256 and SHA-256.
"""

from __future__ import annotations

import datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def generate_root_ca(
    common_name: str = "FreqID Internal Root CA",
    validity_days: int = 3650,
) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    """Generates an internal Root CA keypair and self-signed certificate."""
    ca_key = ec.generate_private_key(ec.SECP256R1())

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "FreqID Security Infrastructure"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )

    now = datetime.datetime.now(datetime.timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=validity_days))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=1),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return ca_cert, ca_key


def issue_device_certificate(
    ca_cert: x509.Certificate,
    ca_key: ec.EllipticCurvePrivateKey,
    device_id: str,
    validity_days: int = 90,
) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    """Issues an edge device client authentication certificate signed by the Root CA."""
    device_key = ec.generate_private_key(ec.SECP256R1())

    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "FreqID Edge Network"),
            x509.NameAttribute(NameOID.COMMON_NAME, device_id),
        ]
    )

    now = datetime.datetime.now(datetime.timezone.utc)
    device_cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(device_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=validity_days))
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=True,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=True,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(device_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return device_cert, device_key


def verify_device_certificate(
    cert: x509.Certificate,
    ca_cert: x509.Certificate,
    revoked_serials: set[int] | None = None,
) -> str:
    """
    Cryptographically verifies an incoming client certificate against the Root CA.
    Enforces validity timeframe, CA signature, and serial revocation checks.
    Returns the device_id extracted from CommonName.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    if now < cert.not_valid_before_utc:
        raise ValueError("Certificate is not yet valid.")
    if now > cert.not_valid_after_utc:
        raise ValueError("Certificate has expired.")

    if revoked_serials and cert.serial_number in revoked_serials:
        raise ValueError(f"Certificate serial {cert.serial_number} is revoked.")

    # Cryptographic signature verification using CA public key
    ca_pub = ca_cert.public_key()
    if not isinstance(ca_pub, ec.EllipticCurvePublicKey):
        raise TypeError("Expected EC CA public key.")

    ca_pub.verify(
        cert.signature,
        cert.tbs_certificate_bytes,
        ec.ECDSA(hashes.SHA256()),
    )

    # Extract device_id from CN
    cns = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if not cns or not cns[0].value:
        raise ValueError("Certificate CommonName is missing.")
    return str(cns[0].value)


def issue_server_certificate(
    ca_cert: x509.Certificate,
    ca_key: ec.EllipticCurvePrivateKey,
    hostname: str = "localhost",
    ip_addresses: list[str] | None = None,
    validity_days: int = 90,
    expired: bool = False,
) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    """Issues a server TLS certificate signed by the Root CA."""
    server_key = ec.generate_private_key(ec.SECP256R1())

    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "FreqID Infrastructure"),
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        ]
    )

    now = datetime.datetime.now(datetime.timezone.utc)
    if expired:
        not_before = now - datetime.timedelta(days=validity_days + 30)
        not_after = now - datetime.timedelta(days=1)
    else:
        not_before = now - datetime.timedelta(minutes=5)
        not_after = now + datetime.timedelta(days=validity_days)

    sans: list[x509.GeneralName] = [x509.DNSName(hostname)]
    if ip_addresses:
        import ipaddress

        for ip in ip_addresses:
            sans.append(x509.IPAddress(ipaddress.ip_address(ip)))

    server_cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=True,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=True,
        )
        .add_extension(
            x509.SubjectAlternativeName(sans),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return server_cert, server_key


def export_pem(
    cert: x509.Certificate,
    private_key: ec.EllipticCurvePrivateKey | None = None,
) -> tuple[str, str | None]:
    """Exports X.509 certificate and private key in PEM format."""
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    key_pem = None
    if private_key:
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")
    return cert_pem, key_pem
