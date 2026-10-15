# FreqID TLS Certificates Directory

This directory stores X.509 Root CA certificates and edge device certificates used for mutual TLS (mTLS) authentication.

## Provisioning Internal Root CA

To generate an internal root CA keypair:
```bash
python scripts/generate_device_cert.py init-ca --out-dir deploy/tls/certs
```
This generates:
- `ca.crt`: Root CA certificate (safe for distribution to edge devices and browser trust store).
- `ca.key`: Root CA private key (mode 0600; keep strictly offline and never commit to git).

## Issuing Device Client Certificates

To issue a client certificate for an edge device:
```bash
python scripts/generate_device_cert.py issue-device \
    --device-id "kiosk-front-door" \
    --ca-cert deploy/tls/certs/ca.crt \
    --ca-key deploy/tls/certs/ca.key \
    --out-dir deploy/tls/certs
```

## Production Public Certificates

If deploying with an external public domain (e.g. `freqid.example.com`), Caddy automatically requests and renews valid TLS certificates via Let's Encrypt / ZeroSSL without requiring manual certificate files here.
