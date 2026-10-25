# FreqID Production Release Checklist

This checklist defines the mandatory operational, cryptographic, and security criteria required prior to tagging and publishing an official FreqID production release.

---

## 1. Automated Test Suite & Code Quality Sign-Off

- [x] **`freqid-core` Test Suite**:
  - All unit tests pass: `pytest core/tests/` (100% pass rate).
  - Umeyama alignment, Block-DCT transform, and ONNX export verified.
- [x] **`freqid-server` Test Suite**:
  - All API routes and models pass: `pytest backend/tests/test_api.py`.
  - Security controls pass: `pytest backend/tests/test_security.py` and `test_phase6_security.py`.
  - Envelope encryption & key hierarchy pass: `pytest backend/tests/test_payload_envelope.py test_key_hierarchy.py`.
- [x] **`freqid-client` SDK Test Suite**:
  - Transport, authentication, retry backoff, and signature verification pass: `pytest client-sdk/tests/`.
- [x] **`admin-ui` Test Suite & Invariant Audits**:
  - Vitest component tests pass: `pnpm test`.
  - Zero-camera invariant check passes: `pnpm check:no-camera` (zero `getUserMedia`, `<video>`, or image input).
  - API schema drift check passes: `pnpm check:api` (zero diff against `backend/openapi.json`).
  - Production build succeeds without warnings: `pnpm build`.

---

## 2. Security & Cryptographic Verifications

- [x] **Zero Raw Images Invariant**:
  - Confirmed raw pixel frames are destroyed on edge devices immediately following Block-DCT frequency extraction.
  - Caddy ingress enforces `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()`.
  - Content Security Policy enforces `frame-ancestors 'none'`, no external scripts, and strict origin isolation.
- [x] **Production Score Masking**:
  - `FREQID_SERVER_MASK_SCORES_IN_PRODUCTION=true` verified.
  - Verification API responses return `similarity: null` to prevent hill-climbing facial reconstruction.
- [x] **Anti-Enumeration Neutral Baseline**:
  - Verifying non-enrolled identities returns `200 OK` with `is_match: false` within 0.16 µs of genuine mismatches.
- [x] **Cryptographic Audit Hash Chaining**:
  - `FREQID_SERVER_AUDIT_ENABLE_HASH_CHAIN=true` active.
  - Continuous SHA-256 hash chaining populated across all events (`has_hash = t`).
- [x] **Repository Secret & Safety Audit**:
  - Pre-commit safety scan passes with zero violations: `python scripts/precommit_check.py --all`.
  - Zero private keys, real `.env` files, database dumps, or raw facial imagery committed to git.

---

## 3. Deployment, Orchestration & Disaster Recovery

- [x] **Container Security Hardening**:
  - Non-root system users (`UID:GID 1000:1000`) enforced across `server` and `admin-ui`.
  - `read_only: true` root filesystems enabled with bounded tmpfs mounts.
  - Linux capabilities dropped (`cap_drop: [ALL]`) and `no-new-privileges: true` set.
- [x] **Trivy Vulnerability Scanning**:
  - Container images scanned for CVEs via GitHub Actions workflow (`.github/workflows/security.yml`).
- [x] **Automated Backup & Disaster Recovery Drill**:
  - `deploy/scripts/backup.sh` generates valid OpenSSL AES-256-CBC encrypted dump with SHA-256 checksum.
  - `deploy/scripts/restore.sh` successfully decrypts and restores full PostgreSQL state.
- [x] **Database Schema Migration Rollback Drill**:
  - Rollback verified: `docker compose run --rm migrate downgrade -1`.
  - Re-upgrade verified: `docker compose run --rm migrate upgrade head` with automated orphan FK cleanup.
- [x] **Observability Verification**:
  - Prometheus `/metrics` operational endpoint verified (`freqid_up`, `freqid_store_connected`, `freqid_enrolled_identities`).

---

## 4. Documentation & Compliance Sign-Off

- [x] **Root `README.md`**:
  - Accurate architecture diagram, quickstart guide, security summary, and documentation links.
- [x] **Installation & Device Setup Guides**:
  - Docker Compose guide in `docs/install.md`.
  - Edge client and pairing guide in `docs/device-setup.md`.
- [x] **Defensible Security Claims**:
  - Formal threat model and empirical attack metrics in `docs/security-claims.md`.
  - Zero unscientific claims ("100% secure", "unhackable", "eliminates risk").
- [x] **Licensing & Attributions**:
  - Apache-2.0 headers present on all source files.
  - Third-party dependency audit and Tencent/TFace attributions in `docs/assets-and-licenses.md`.
- [x] **Vulnerability Disclosure Policy**:
  - Security policy and private reporting channels in `SECURITY.md`.

---

## 5. Release Tagging & Publication Procedure

1. Verify working tree is clean:
   ```bash
   git status
   ```
2. Run full repository safety scan:
   ```bash
   python scripts/precommit_check.py --all
   ```
3. Push final release commits to `origin phase9-release`.
4. Open Pull Request to merge `phase9-release` into the main development branch of the fork (`p19racha/FreqID`).
5. Upon PR approval and merge, tag the release:
   ```bash
   git tag -a v0.1.0 -m "Release v0.1.0: Production-hardened self-hosted privacy-preserving face recognition"
   git push origin v0.1.0
   ```
6. GitHub Actions release workflow (`.github/workflows/release.yml`) builds and publishes multi-platform Docker container images and packages release assets.
