#!/usr/bin/env python3
# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
generate_device_cert.py: Command-line utility to provision internal CA and device certificates for mTLS.
"""

import argparse
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from freqid_server.crypto.ca import (
    export_pem,
    generate_root_ca,
    issue_device_certificate,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision FreqID Internal CA and Edge Device Certificates")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init-ca
    ca_parser = subparsers.add_parser("init-ca", help="Generate root CA keypair and self-signed certificate")
    ca_parser.add_argument("--out-dir", type=Path, default=Path("deploy/tls/certs"), help="Output directory")
    ca_parser.add_argument("--validity-days", type=int, default=3650, help="CA validity in days")

    # issue-device
    dev_parser = subparsers.add_parser("issue-device", help="Issue client certificate for an edge device")
    dev_parser.add_argument("--device-id", type=str, required=True, help="Edge device unique identifier (CN)")
    dev_parser.add_argument("--ca-cert", type=Path, default=Path("deploy/tls/certs/ca.crt"), help="Root CA cert path")
    dev_parser.add_argument("--ca-key", type=Path, default=Path("deploy/tls/certs/ca.key"), help="Root CA key path")
    dev_parser.add_argument("--out-dir", type=Path, default=Path("deploy/tls/certs"), help="Output directory")
    dev_parser.add_argument("--validity-days", type=int, default=90, help="Device cert validity in days")

    args = parser.parse_args()

    if args.command == "init-ca":
        args.out_dir.mkdir(parents=True, exist_ok=True)
        ca_cert, ca_key = generate_root_ca(validity_days=args.validity_days)
        cert_pem, key_pem = export_pem(ca_cert, ca_key)

        (args.out_dir / "ca.crt").write_text(cert_pem)
        (args.out_dir / "ca.key").write_text(key_pem or "")
        (args.out_dir / "ca.key").chmod(0o600)
        print(f"Successfully generated Root CA in {args.out_dir}: ca.crt, ca.key (mode 0600)")

    elif args.command == "issue-device":
        if not args.ca_cert.is_file() or not args.ca_key.is_file():
            raise FileNotFoundError(f"CA files not found: {args.ca_cert}, {args.ca_key}")

        ca_cert = x509.load_pem_x509_certificate(args.ca_cert.read_bytes())
        raw_key = serialization.load_pem_private_key(args.ca_key.read_bytes(), password=None)
        if not isinstance(raw_key, ec.EllipticCurvePrivateKey):
            raise TypeError(f"CA private key must be EllipticCurvePrivateKey, got {type(raw_key).__name__}")
        loaded_ca_key: ec.EllipticCurvePrivateKey = raw_key

        dev_cert, dev_key = issue_device_certificate(
            ca_cert=ca_cert,
            ca_key=loaded_ca_key,
            device_id=args.device_id,
            validity_days=args.validity_days,
        )
        cert_pem, key_pem = export_pem(dev_cert, dev_key)

        args.out_dir.mkdir(parents=True, exist_ok=True)
        cert_file = args.out_dir / f"{args.device_id}.crt"
        key_file = args.out_dir / f"{args.device_id}.key"

        cert_file.write_text(cert_pem)
        key_file.write_text(key_pem or "")
        key_file.chmod(0o600)
        print(f"Issued device certificate for '{args.device_id}' in {args.out_dir}: {cert_file.name}, {key_file.name}")


if __name__ == "__main__":
    main()
