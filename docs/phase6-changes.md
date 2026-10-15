# Phase 6 Changes & Adaptations

This document details all modifications, additions, and architectural adaptations made during Phase 6 (Device Network, Admin Accounts, and Admin API). In strict accordance with Hard Rule 1, changes were confined to the identity, device pairing, and administrative layers of `freqid-server` and `freqid-client`. Upstream TFace (`recognition/`) and `freqid_core` remain 100% untouched.

---

## 1. Upstream & Sibling Packages (Hard Rule Invariants)

- **`recognition/` (Upstream Tencent/TFace)**: **ZERO modifications.** No files added, modified, or deleted.
- **`core/` (`freqid_core`)**: **ZERO modifications.** Binary wire format (`PartialFacePayload`), Block Discrete Cosine Transform math, IR-18 neural backbone, and ONNX export remain byte-for-byte identical to Phase 2.
- **`client-sdk/` (`freqid_client`)**: Extended strictly to support the edge device pairing flow and per-request Ed25519 HTTP signatures. Core face detection, landmark alignment, quality gates, and spatial frame zeroing memory invariants remain untouched.

---

## 2. Database Migrations & Models (`backend/alembic/`, `backend/src/freqid_server/storage/`)

### 2.1 Database Schema Migration
- **Script**: `backend/alembic/versions/a1b2c3d4e5f6_phase6_admin_and_devices.py`
- **Tables Created**:
  1. `admin_users`: Stores administrator credentials, Argon2id hashes, roles (`owner`, `admin`, `operator`, `auditor`), failed login counters, lockout timestamps, and optional TOTP secrets.
  2. `admin_refresh_tokens`: Stores rotating refresh tokens hashed with SHA-256, grouped by `family_id` for token theft detection.
  3. `devices`: Edge device registry storing device UUID, name, Ed25519 public key in PEM format, lifecycle state (`pending`, `active`, `suspended`, `revoked`), last seen timestamp, client IP, and software version.
  4. `pairing_tokens`: Stores single-use edge pairing tokens hashed with SHA-256, expiration timestamps, and consumption audit timestamps.
  5. `device_heartbeats`: Time-series device health telemetry storing recorded latency, queued payloads, free storage, and status.
  6. `system_settings`: Key-value JSONB settings store tracking configuration overrides, updated timestamps, and modifier admin UUIDs.
- **Foreign Key Adaptations**:
  - `audit_events.device_id` and `admin_id` altered from plain text strings to UUID foreign keys with `ON DELETE SET NULL`.
  - `enrollment_sessions.device_id` altered to UUID foreign key with `ON DELETE SET NULL`.

### 2.2 SQLAlchemy 2.0 ORM Mappings (`models.py`)
- Created `AdminUserOrm`, `AdminRefreshTokenOrm`, `DeviceOrm`, `PairingTokenOrm`, `DeviceHeartbeatOrm`, and `SystemSettingOrm`.
- Updated `AuditEventOrm` with foreign keys to `devices.id` and `admin_users.id`.

### 2.3 Role Privilege Separation (`docs/phase6-db-roles.md`)
- Granted operational application role (`freqid_app`) permissions (`SELECT`, `INSERT`, `UPDATE`, `DELETE`) on all Phase 6 operational tables, while maintaining strict `NO DELETE` / `NO UPDATE` restrictions on `audit_events`.
- Granted maintenance role (`freqid_maint`) permissions to prune expired pairing tokens, heartbeats, and revoked refresh tokens.

---

## 3. Cryptographic & Security Subsystems (`backend/src/freqid_server/auth/`)

### 3.1 Passwords & Anti-Enumeration (`passwords.py`)
- Implemented RFC 9106 Argon2id password hashing using `argon2-cffi` ($64\text{ MiB}$ memory cost, 3 iterations, 4 parallelism lanes).
- Added password complexity validator enforcing 12-character minimum and rejecting passwords contained in the top 10,000 common password dictionary.
- Built constant-time baseline dummy hash computation: when a non-existent username is submitted during login, the system runs an identical Argon2id calculation against a static hash, eliminating timing enumeration side-channels.

### 3.2 Role-Based Access Control (`rbac.py`)
- Formalized 4 administrative tiers:
  - `owner`: Unrestricted administrative rights, including managing other owners and updating system settings.
  - `admin`: Full identity and device management, pairing token issuance, audit log reading and CSV export.
  - `operator`: Day-to-day operational visibility and user/device status viewing.
  - `auditor`: Read-only access to system health, audit logs, and compliance CSV exports.
- Implemented `@require_permission(perm)` route decorator enforcing permission verification before handler execution.

### 3.3 Admin Tokens & Session Rotation (`admin_tokens.py`)
- **JWT Access Tokens**: Short-lived (15 minutes), signed with `HS256`, containing admin ID, username, role, and granted permissions.
- **Refresh Tokens & Family Revocation**: Long-lived (7 days) cryptographically random tokens stored as SHA-256 hashes. Upon refresh, the previous token is marked `is_revoked = True` and a new token is issued in the same family. If an already-revoked refresh token is ever submitted, the server detects token reuse, revokes all tokens across the entire `family_id`, and alerts an audit event.

### 3.4 Progressive Account & IP Lockouts (`lockout.py`)
- Built `LockoutManager` tracking consecutive failed login attempts across both username and client IP.
- Enforces progressive backoff: 5 failures lock the account/IP for 15 minutes, with exponential doubling on successive lockout events ($15\text{m} \to 30\text{m} \to 60\text{m}$).

### 3.5 Device Cryptography (`device_crypto.py`)
- Implemented Ed25519 keypair generation, public key PEM export, and signature verification via `cryptography.hazmat.primitives.asymmetric.ed25519`.
- Defined canonical message serialization format for HTTP requests:
  $$\text{CANONICAL\_STRING} = \text{METHOD} + \text{"\\n"} + \text{PATH} + \text{"\\n"} + \text{TIMESTAMP} + \text{"\\n"} + \text{NONCE} + \text{"\\n"} + \text{SHA256}(\text{BODY})$$

### 3.6 Unified Authenticator (`authenticator.py`)
- Dispatches authentication based on incoming headers:
  - **Admin Principal**: Decodes and validates `Authorization: Bearer <JWT>` against current token blacklist and admin status.
  - **Device Principal**: Validates `X-Device-ID`, `X-Timestamp`, `X-Nonce`, and `X-Signature`.
- **Sliding Timestamp Window**: Verifies that $|t_{\text{client}} - t_{\text{server}}| \le 300\text{ seconds}$.
- **In-Memory Nonce Deduplication**: Deduplicates nonces in memory with automatic time-to-live expiration, preventing replay attacks.
- **Immediate Revocation ($0\text{ ms}$ delay)**: Queries device state on every request; transitions to `revoked` or `suspended` take effect instantly on the very next incoming packet.

---

## 4. Administrative Command-Line Interface (`backend/src/freqid_server/admin_cli.py`)

Added `freqid-admin` CLI executable:
- `create-owner --username <name>`: Bootstraps the root system owner interactively via `getpass.getpass()`. Aborts if an active owner already exists unless `--force` is supplied.
- `reset-password --username <name>`: Emergency password reset for locked or compromised accounts without third-party email services.
- `unlock --username <name>`: Clears failed login counters and unlocks an administrative account.
- `list-admins`: Lists all administrators, roles, active statuses, and lockout deadlines.
- `disable-admin --username <name>`: Instantly disables an administrative account.

---

## 5. Admin API Surface (`backend/src/freqid_server/api/`)

Implemented 39 REST endpoints supporting the upcoming Phase 7 management UI:

### 5.1 Admin Authentication (`routes_admin_auth.py`)
- `POST /v1/admin/auth/login`: Authenticates administrator, returns short-lived JWT, and sets `HttpOnly; Secure; SameSite=Lax` refresh cookie.
- `POST /v1/admin/auth/refresh`: Rotates refresh token and issues new JWT.
- `POST /v1/admin/auth/logout`: Revokes refresh token and clears session cookies.
- `GET /v1/admin/auth/me`: Returns current administrator profile, role, and permissions.
- `POST /v1/admin/auth/change-password`: Self-service password change requiring current password verification.
- `POST /v1/admin/auth/mfa/setup`, `/verify`, `/disable`: RFC 6238 TOTP lifecycle management.

### 5.2 Device Registry Management (`routes_admin_devices.py`)
- `GET /v1/admin/devices`: Filterable, paginated device list with health status.
- `POST /v1/admin/devices/pairing-tokens`: Generates 32-character high-entropy single-use pairing token expiring in 15 minutes.
- `GET /v1/admin/devices/pairing-tokens`: Lists pending pairing tokens.
- `DELETE /v1/admin/devices/pairing-tokens/{id}`: Cancels a pending pairing token.
- `GET /v1/admin/devices/{id}`: Detailed telemetry and metadata for an edge device.
- `PATCH /v1/admin/devices/{id}`: Renames or annotates an edge device.
- `POST /v1/admin/devices/{id}/suspend`: Temporarily suspends device access.
- `POST /v1/admin/devices/{id}/resume`: Restores suspended device to active.
- `POST /v1/admin/devices/{id}/revoke`: Permanently revokes device credentials ($0\text{ ms}$ delay).
- `DELETE /v1/admin/devices/{id}`: Removes device record from database.

### 5.3 Device Edge Communication (`routes_devices.py`)
- `POST /v1/devices/pair`: Edge device pairing endpoint. Consumes pairing token atomically, registers Ed25519 public key, and returns device UUID.
- `POST /v1/devices/heartbeat`: Receives signed edge health telemetry and records metrics in `device_heartbeats`.

### 5.4 User Management Surface (`routes_admin_users.py`)
- `GET /v1/admin/users`: Search and paginate enrolled users with template quality summaries.
- `GET /v1/admin/users/{id}`: User profile and template details.
- `PATCH /v1/admin/users/{id}`: Updates user metadata.

### 5.5 System & Audit Management (`routes_admin_system.py`)
- `GET /v1/admin/admins`, `POST`, `PATCH`, `DELETE`: Administrator account provisioning and lifecycle management.
- `GET /v1/admin/system/status`: Real-time database pool, vector gallery, and host telemetry.
- `GET /v1/admin/system/settings`, `PATCH`: Manages configurable runtime thresholds.
- `GET /v1/admin/system/audit`: Paginated search across structured audit events.
- `GET /v1/admin/system/audit/export`: Streams tamper-evident audit records directly to CSV.

---

## 6. Client SDK Enhancements (`client-sdk/src/freqid_client/`)

### 6.1 Authentication Module (`auth.py`)
- Built `DeviceSignatureAuthenticator`:
  - Generates Ed25519 keypairs locally using `cryptography`.
  - Serializes and stores credentials (`device_id`, `private_key_pem`, `server_url`, `key_id`) to JSON files with strict POSIX `0600` permissions. Refuses to load files with insecure permissions.
  - Implements `.authenticate(headers, method, path, content)` by appending `X-Device-ID`, `X-Timestamp`, `X-Nonce`, and the computed Ed25519 `X-Signature`.
- Implemented `pair_device(...)` orchestrating the atomic pairing handshake against `/v1/devices/pair`.

### 6.2 Transport Module (`transport.py`)
- Integrated `DeviceSignatureAuthenticator` into `FreqIDTransport`. All outgoing biometric requests (`verify`, `identify`, `enroll`, and `heartbeat`) automatically sign the full request body digest `SHA256(content)`.

### 6.3 Client CLI (`cli.py`)
- Added `freqid-client pair` command:
  ```bash
  freqid-client pair --server http://127.0.0.1:8000 --token <tok> --name "cam-01" --credentials ~/.freqid/creds.json
  ```
- Added `freqid-client status` command inspecting local credential permissions and testing server connectivity.

---

## 7. Verification & Parity Audit

- **Test Suite Results**:
  - `backend/tests/test_phase6_security.py`: **10 / 10 passed (100%)** testing default-deny, RBAC permission enforcement, pairing token race safety, instant revocation, replay attacks, anti-enumeration timing, refresh token family reuse detection, and secret redaction.
  - `backend/tests/test_phase6_integration_benchmarks.py`: **2 / 2 passed (100%)** testing live end-to-end client pairing, 0600 storage, verification, and concurrent load.
  - **Full repository pass rate**: **116 passed, 0 failed** (62 in `backend/tests/`, 27 in `client-sdk/tests/`, 27 in `core/tests/`).
