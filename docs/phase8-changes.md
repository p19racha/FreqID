# FreqID Phase 8: Changes & Architecture Modifications

This document lists all modifications and additions made across the FreqID codebase in Phase 8 (Cryptography, Key Management, Template Protection, and Attack Evaluation).

## 1. Zero-Modification Invariant Verification
- **`recognition/` (Upstream Tencent/TFace):** ZERO modifications made. All original files unmodified.
- **`core/` (`freqid_core`):** ZERO modifications made. Mathematical transforms, DCT extraction, and embedding algorithms remain untouched.

## 2. Added Components

### Transport Security & Internal PKI
- **`deploy/tls/nginx-tls13.conf`**: Strict TLS 1.3 reverse proxy configuration with cipher suites, curve preferences, and mTLS verification.
- **`deploy/tls/traefik-tls13.yml`**: Modern Traefik dynamic TLS 1.3 configuration with client certificate authorities.
- **`deploy/tls/verification_checklist.md`**: Step-by-step audit guide using `openssl s_client`, `testssl.sh`, and `curl` for transport validation.
- **`backend/src/freqid_server/crypto/ca.py`**: Internal Certificate Authority engine managing P-256 root CA and device certificate issuing/verification.
- **`scripts/generate_device_cert.py`**: Administrative CLI generating device mTLS certificates signed by internal CA.

### Application-Layer Payload Sealing
- **`backend/src/freqid_server/crypto/payload_envelope.py`**:
  - Binary `PF02` envelope format parser and serializer.
  - Ephemeral-static X25519 ECDH key exchange.
  - HKDF-SHA256 key derivation with nonce salt.
  - AES-256-GCM authenticated encryption.
  - Ed25519 device signature binding.
  - In-memory sliding-window TTL replay cache (`ReplayDetector`).
  - Helper `unseal_request_payload` for automatic unsealing on verification, identification, and enrollment routes.
- **`client-sdk/src/freqid_client/crypto/payload_envelope.py`**: Client-side mirror for ephemeral sealing.
- **`backend/src/freqid_server/api/routes_payload_key.py`**: Public endpoint (`GET /v1/payload-key`) publishing active server X25519 public key.

### Key Hierarchy & Shamir Secret Sharing
- **`backend/src/freqid_server/crypto/provider.py`**:
  - Added HKDF subkey derivation (`derive_purpose_key` for `template`, `transform`, `audit`, `token`, `payload`).
  - Added X25519 static payload keypair derivation.
  - Added `KeyHierarchy` dataclass.
- **`backend/src/freqid_server/cli_keys.py`** & **`scripts/freqid_keys.py`**:
  - `generate`: Cryptographically secure 256-bit master key generator with 0600 file permissions.
  - `split`: $K$-of-$N$ Shamir Secret Sharing using audited SLIP-0039 standard (`shamir-mnemonic`).
  - `combine`: Threshold secret reconstruction from $K$ mnemonic shares.
  - `subkeys`: Inspection of subkey SHA-256 fingerprints.

### Cancelable Keyed Orthogonal Template Transformation
- **`backend/src/freqid_server/crypto/template_transform.py`**:
  - Deterministic Haar-measure orthogonal matrix generation $R \in \mathbb{O}(512)$ from HKDF transform subkey.
  - Exact isometry: $\langle R u, R v \rangle \equiv \langle u, v \rangle$ ($\Delta\text{TAR} = 0.00\%$).
  - Transformation and inversion functions with caching.
- **`backend/src/freqid_server/crypto/envelope.py`**:
  - Support for `format_version = 2` applying orthogonal transformation $R$ prior to AES-256-GCM encryption.
  - Dual-read backwards compatibility with `format_version = 1`.
- **`scripts/migrate_templates.py`**:
  - Zero-downtime batch migration CLI converting v1 templates to v2 rotated templates.

### Information Leakage & Anomaly Controls
- **`backend/src/freqid_server/services/anomaly_detector.py`**:
  - `NearThresholdAnomalyDetector` tracking verification attempts landing in $[\tau - 0.05, \tau + 0.05]$.
  - Flags clustering indicative of hill-climbing attacks.
- **`backend/src/freqid_server/services/matching.py`**:
  - Decision-only output default for production callers.
  - `quantize_and_noise_score` adding discrete rounding ($\Delta s = 0.05$) and calibrated Laplace noise ($\epsilon = 2.0$).

### Empirical Evaluation Suite (`security-eval/`)
- **`eval_01_payload_reconstruction.py`**: Mathematical IDCT inversion & spatial reconstruction yield.
- **`eval_02_template_inversion.py`**: Unkeyed feature recovery & inversion success rate.
- **`eval_03_cross_system_linkage.py`**: Cross-system correlation & False Link Rate at $\tau = 0.35$.
- **`eval_04_hill_climbing.py`**: Hill-climbing against continuous, quantized/noised, and decision-only outputs.
- **`eval_05_protocol_tampering.py`**: Fuzzing and tampering of sealed payload envelopes.
- **`eval_06_proxy_eavesdropping.py`**: Compromised reverse proxy capture simulation.
- **`eval_07_database_dump_integrity.py`**: Full database dump analysis & offline cracking resistance.
- **`eval_08_timing_side_channels.py`**: 1:1 verify latency distribution & anti-enumeration timing test.
- **`run_all_evals.py`**: Automated runner outputting JSON results and summary table.

## 3. Minimal Modifications to Existing Code

### `client-sdk/src/freqid_client/transport.py` & `config.py`
- Added TLS 1.3 / mTLS client certificate configuration (`client_cert_path`, `client_key_path`).
- Added SHA-256 certificate pinning (`pinned_cert_fingerprint`).
- Added application-layer payload sealing (`seal_payloads`, `server_payload_public_key_hex`, `payload_key_id`).
- Automatically fetches and caches server X25519 public key if not configured statically.

### `backend/src/freqid_server/main.py`
- Instantiated `key_provider`, `ReplayDetector`, and `NearThresholdAnomalyDetector` on `app.state`.
- Mounted `routes_payload_key.router`.

### `backend/src/freqid_server/api/routes_verify.py`, `routes_identify.py`, `routes_enroll.py`
- Added seamless payload unsealing via `unseal_request_payload` prior to parsing `PartialFacePayload`.
- Retains backwards compatibility for unsealed payloads during migration.
- Emits `security_anomaly` audit event when `NearThresholdAnomalyDetector` flags hill-climbing patterns.

### `backend/src/freqid_server/api/routes_admin_system.py` & `schemas.py`
- Added `GET /v1/admin/security/status` endpoint reporting cryptographic posture, template migration counts, and anomaly detector telemetry.

### `admin-ui/src/features/status/SystemStatus.tsx`
- Added Cryptographic Posture & Template Protection telemetry card.
