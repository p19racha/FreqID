# freqid-server: Inference & Matching Server

`freqid-server` is the central biometric matching service of the **FreqID** privacy-preserving facial recognition system. Built on FastAPI and ONNX Runtime, it accepts **only partial frequency payloads** ($27$-channel DCT representations) over TLS. Spatial face images (JPEG, PNG, BMP, raw pixels) are strictly prohibited and architecturally rejected.

---

## Key Privacy & Security Guarantees

1. **Strict Architectural Isolation (Hard Rule 2)**:
   - The server **never** imports `cv2`, `PIL`, `torchvision`, or `freqid_core.transform`.
   - The server codebase has no ability to decode spatial images or compute DCT representations.
2. **Raw Image Binary Rejection (Hard Rule 3)**:
   - Spatial image MIME types (`image/*`) are rejected with `HTTP 415 Unsupported Media Type`.
   - Magic byte header inspection rejects JPEG (`\xff\xd8\xff`), PNG (`\x89PNG`), BMP (`BM`), and WebP with `HTTP 400 IMAGE_DATA_REJECTED`.
3. **Automated Biometric Redaction (Hard Rule 4)**:
   - A custom logging filter (`BiometricRedactionFilter`) scrubs all floating-point embedding vectors and binary payload sequences from all logger streams before standard output or log storage.
4. **Envelope Encryption at Rest (Phase 5)**:
   - Every 512-D template is encrypted using AES-256-GCM with a unique per-template Data Encryption Key (DEK).
   - Each DEK is wrapped using RFC 3394 AES Key Wrap with a master key (`KEK`).
   - Authenticated Additional Data (AAD) cryptographically binds the ciphertext to the user's UUID and model version, preventing cross-identity ciphertext transplant attacks.
5. **Least-Privilege Database Isolation (Phase 5)**:
   - Operational application role (`freqid_app`) has zero `DDL` rights and zero `DELETE` or `UPDATE` rights on `audit_events`.
   - Administrative migrations run via `freqid_admin`.
   - Retention pruning runs via dedicated `freqid_maint` role.
6. **Anti-Enumeration Protection**:
   - Verification requests for non-existent identities execute a balanced forward projection against a neutral baseline vector before returning `is_match: False`, eliminating timing side-channels that would leak user existence.
7. **Score Masking**:
   - In production environments, raw floating-point cosine similarities are omitted from verification responses for non-admin callers, preventing hill-climbing facial reconstruction attacks.
8. **Replay & Rate-Limit Defense**:
   - Nonces (`X-Nonce`) are verified with sliding-window deduplication (`REPLAY_DETECTED`).
   - Consecutive failed verifications trigger temporary identity-level lockout to prevent brute-force attacks.

---

## Architectural Layout

```
backend/
├── pyproject.toml              # Build config, dependencies, console scripts
├── Dockerfile                  # Multi-stage production container image
├── alembic.ini                 # Database migration configuration
├── alembic/                    # Async SQLAlchemy Alembic migration scripts
│   ├── env.py                  # Migration runner (SQL parameter redaction enforced)
│   └── versions/               # Schema revisions (001_initial_phase5_schema.py)
├── openapi.json                # Exported OpenAPI 3.1 specification
├── scripts/
│   ├── audit_retention.py      # Automated audit log retention policy purger
│   ├── benchmark_phase5.py     # Gallery load, key rotation & verify latency benchmarks
│   ├── benchmark_search.py     # 1:N vector gallery scaling benchmark
│   ├── export_openapi.py       # OpenAPI schema generator
│   ├── load_test.py            # Concurrent load & latency measurement tool
│   ├── rotate_keys.py          # Master key re-wrapping script (7,400+ records/sec)
│   └── verify_audit_chain.py   # Tamper-evident audit log cryptographic verification
├── src/freqid_server/
│   ├── api/                    # Route endpoints & schemas
│   │   ├── routes_verify.py    # POST /v1/verify
│   │   ├── routes_identify.py  # POST /v1/identify
│   │   ├── routes_enroll.py    # POST /v1/enroll, DELETE, export, enable/disable
│   │   ├── routes_health.py    # GET /healthz, /readyz, /v1/model
│   │   └── schemas.py          # Pydantic request & response models
│   ├── audit/                  # Non-blocking asynchronous audit subsystem
│   │   ├── base.py             # AuditEvent dataclass, coarse score bucketing, IP hashing
│   │   └── postgres.py         # PostgresAuditSink with batching & load shedding
│   ├── auth/                   # Pluggable authentication interfaces
│   │   ├── base.py             # AuthenticatedPrincipal & ABC
│   │   └── static_token.py     # Constant-time token authenticator
│   ├── crypto/                 # Envelope encryption & key management
│   │   ├── envelope.py         # TemplateEncryptor (AES-256-GCM + RFC 3394 Key Wrap)
│   │   └── provider.py         # EnvOrFileKeyProvider with POSIX 0600 validation
│   ├── services/               # Core business & neural logic
│   │   ├── inference.py        # ThreadPoolExecutor ONNX inference service
│   │   ├── gallery.py          # Copy-on-Write in-memory vector index
│   │   ├── matching.py         # 1:1 verify & 1:N formatters
│   │   └── enrollment.py       # Multi-sample synthesis, outlier rejection & batch unpack
│   ├── storage/                # Persistence layer
│   │   ├── base.py             # TemplateStore abstract interface & StoredTemplate
│   │   ├── memory.py           # Thread-safe in-memory store with version tracking
│   │   ├── models.py           # SQLAlchemy 2.0 ORM mappings (User, Template, AuditEvent)
│   │   └── postgres.py         # PostgreSQLTemplateStore with optimistic locking
│   ├── config.py               # Pydantic-settings configuration
│   ├── errors.py               # Typed exception hierarchy
│   ├── logging.py              # Redacted structured JSON logging
│   ├── middleware.py           # Security, magic bytes & rate-limiting middleware
│   └── main.py                 # FastAPI app factory & Uvicorn runner
└── tests/                      # Automated test suite (50 passed, 89% coverage)
```

---

## Configuration & Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `FREQID_STORE_BACKEND` | `postgres` | Storage backend: `postgres` or `memory` |
| `FREQID_DATABASE_URL` | `postgresql+asyncpg://freqid_app:...@127.0.0.1:54322/freqid` | Async PostgreSQL connection string |
| `FREQID_DATABASE_POOL_SIZE` | `20` | Connection pool size for asyncpg |
| `FREQID_DATABASE_MAX_OVERFLOW` | `10` | Max overflow connections beyond pool size |
| `FREQID_DATABASE_ECHO` | `false` | Must stay `false` in production to prevent SQL parameter leakage |
| `FREQID_ACTIVE_KEY_VERSION` | `1` | Active master encryption key version for new templates |
| `FREQID_MASTER_KEY_V1` | `""` | 256-bit AES master key in hex format |
| `FREQID_KEY_DIR` | `None` | Path to key directory for file-based keys (`key_v<N>.key` with POSIX `0600` permissions) |
| `FREQID_AUDIT_ENABLED` | `true` | Enable non-blocking database audit logging |
| `FREQID_AUDIT_BATCH_SIZE` | `50` | Batch insert size for audit events |
| `FREQID_AUDIT_FLUSH_INTERVAL` | `1.0` | Max seconds before flushing queued audit records |
| `FREQID_AUDIT_QUEUE_CAPACITY` | `10000` | In-memory audit queue capacity before load-shedding |
| `FREQID_AUDIT_TAMPER_EVIDENT` | `false` | Enable SHA-256 running hash chaining across audit log rows |
| `FREQID_ENROLL_DUPLICATE_CHECK` | `true` | Check for existing biometric duplicates during enrollment |
| `FREQID_ENROLL_DUPLICATE_POLICY`| `block` | Duplicate identity policy: `block` (HTTP 409) or `warn` |

---

## Database Management & Migrations

### Database Roles & Least Privilege Model
PostgreSQL database access follows strict least-privilege segregation:
- **`freqid_admin`**: DDL owner. Executes migrations (`alembic upgrade head`).
- **`freqid_app`**: Operational DML role. `SELECT`, `INSERT`, `UPDATE` on `users` and `templates`. `INSERT`, `SELECT` on `audit_events`. **Strictly denied** `UPDATE`, `DELETE`, `TRUNCATE` on `audit_events`.
- **`freqid_maint`**: Dedicated maintenance role for `audit_retention.py` to prune expired audit events.

### Running Migrations
To apply database schema migrations:
```bash
# Set database URL to admin user for migrations
export FREQID_ADMIN_DATABASE_URL="postgresql+asyncpg://freqid_admin:secret@127.0.0.1:54322/freqid"
cd backend
alembic upgrade head
```

To rollback the last migration:
```bash
alembic downgrade -1
```

---

## Operational Runbooks

### 1. Master Key Rotation (`rotate_keys.py`)
FreqID implements envelope encryption. Re-wrapping requires only decrypting the 32-byte DEK with the old master key (`KEK_old`) and re-wrapping it with the new master key (`KEK_new`). The 2,048-byte biometric ciphertext is **never touched or decrypted**, making rotation instantaneous and zero-risk.

```bash
# Provision new master key (e.g., version 2)
export FREQID_MASTER_KEY_V2="<new-64-character-hex-key>"

# Run batch rotation tool
python backend/scripts/rotate_keys.py \
    --database-url "postgresql+asyncpg://freqid_app:secret@127.0.0.1:54322/freqid" \
    --new-version 2 \
    --batch-size 500
```
*Empirical throughput: ~7,440 records/second with zero biometric ciphertext modification.*

### 2. Tamper-Evident Audit Chain Verification (`verify_audit_chain.py`)
When `FREQID_AUDIT_TAMPER_EVIDENT=true`, each audit log record contains a SHA-256 hash chaining back to the previous record's hash. To cryptographically verify that audit records have not been altered, deleted, or inserted:

```bash
python backend/scripts/verify_audit_chain.py \
    --database-url "postgresql+asyncpg://freqid_app:secret@127.0.0.1:54322/freqid"
```

### 3. Audit Log Retention Pruning (`audit_retention.py`)
To comply with GDPR data minimization requirements and clear events older than a specified retention period (e.g., 90 days):

```bash
# Run using the maintenance role
python backend/scripts/audit_retention.py \
    --database-url "postgresql+asyncpg://freqid_maint:secret@127.0.0.1:54322/freqid" \
    --retention-days 90 \
    --batch-size 1000
```

---

## Phase 6 Identity & Device Management

### 1. Edge Device Identity & Pairing Lifecycle
Edge devices authenticate to `freqid-server` using **Ed25519 per-request HTTP signatures**. The device pairing lifecycle follows a secure, single-use token protocol:

```mermaid
sequenceDiagram
    autonumber
    actor Admin as Administrator
    participant Srv as FreqID Server
    participant Edge as Edge Device (freqid-client)

    Admin->>Srv: POST /v1/admin/devices/pairing-tokens (Scope: admin:devices)
    Srv-->>Admin: Returns 32-char high-entropy pairing token (Expires in 15m)
    Admin->>Edge: Provision token to device (freqid-client pair --token <tok>)
    Edge->>Edge: Generate Ed25519 keypair locally
    Edge->>Srv: POST /v1/devices/pair (token, public_key, device_name)
    Srv->>Srv: Verify token & mark used atomically
    Srv->>Srv: Register device (status: active)
    Srv-->>Edge: HTTP 201 Created (device_id, key_id)
    Edge->>Edge: Store credentials with POSIX 0600 permissions
```

#### Edge Device Pairing Runbook
1. **Generate Pairing Token**:
   An administrator generates a single-use pairing token via the Admin API:
   ```bash
   curl -X POST http://127.0.0.1:8000/v1/admin/devices/pairing-tokens \
     -H "Authorization: Bearer <ADMIN_ACCESS_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"name": "front-entrance-cam-1", "expires_in_minutes": 15}'
   ```
   *Response*: `{"token": "f8a9...", "expires_at": "...", "token_id": "..."}`

2. **Execute Edge Pairing**:
   On the camera/edge terminal running `freqid-client`:
   ```bash
   freqid-client pair \
     --server http://127.0.0.1:8000 \
     --token "f8a9..." \
     --name "front-entrance-cam-1" \
     --credentials ~/.freqid/device_credentials.json
   ```
   *Privacy Guarantee*: The private key is generated and stored locally with POSIX `0600` permissions. The private key never leaves the edge device.

3. **Per-Request HTTP Signature Verification**:
   All subsequent requests from the edge device (`/v1/verify`, `/v1/identify`, `/v1/enroll`, `/v1/devices/heartbeat`) include signed headers:
   - `X-Device-ID`: UUID of paired device.
   - `X-Timestamp`: RFC 3339 / ISO 8601 UTC timestamp (validated against a $\pm 300\text{s}$ sliding window).
   - `X-Nonce`: Cryptographically secure unique string (deduplicated in memory to block replay attacks).
   - `X-Signature`: Base64-encoded Ed25519 signature over canonical string `METHOD\nPATH\nTIMESTAMP\nNONCE\nSHA256(BODY)`.

4. **Instant Revocation ($0\text{ ms}$ delay)**:
   When an administrator revokes a device via `POST /v1/admin/devices/{id}/revoke`, the status transitions to `revoked` in PostgreSQL. Because `UnifiedAuthenticator` inspects device status on every incoming request, subsequent signed requests are immediately rejected with `HTTP 401 DEVICE_REVOKED`.

---

### 2. Role-Based Access Control (RBAC) Matrix

FreqID implements four administrative tiers following least privilege:

| Permission | `owner` | `admin` | `operator` | `auditor` | Description |
|---|:---:|:---:|:---:|:---:|---|
| `admin:users:read` | ✅ | ✅ | ✅ | ❌ | View user identities and metadata |
| `admin:users:write` | ✅ | ✅ | ❌ | ❌ | Create, update, enable, disable users |
| `admin:users:delete` | ✅ | ✅ | ❌ | ❌ | Permanent GDPR deletion of users & templates |
| `admin:devices:read` | ✅ | ✅ | ✅ | ❌ | View registered devices and status |
| `admin:devices:write` | ✅ | ✅ | ❌ | ❌ | Create pairing tokens, edit device metadata |
| `admin:devices:revoke`| ✅ | ✅ | ❌ | ❌ | Revoke and suspend edge devices |
| `admin:admins:read` | ✅ | ✅ | ❌ | ❌ | View administrative accounts |
| `admin:admins:write` | ✅ | ❌ | ❌ | ❌ | Create/modify `admin`, `operator`, `auditor` |
| `admin:admins:owner` | ✅ | ❌ | ❌ | ❌ | Manage other `owner` accounts |
| `audit:read` | ✅ | ✅ | ❌ | ✅ | Query structured audit event logs |
| `audit:export_csv` | ✅ | ✅ | ❌ | ✅ | Stream tamper-evident audit logs to CSV |
| `system:read` | ✅ | ✅ | ✅ | ✅ | View server health, version, model status |
| `system:write` | ✅ | ❌ | ❌ | ❌ | Update system settings and retention periods |

---

### 3. Administrative Management CLI (`freqid-admin`)

FreqID provides a command-line tool `freqid-admin` for system bootstrapping, password resets, and emergency account recovery. Passwords are typed interactively and never passed via flags or environment variables.

```bash
# 1. Bootstrap the initial owner account (fails if active owner exists)
freqid-admin create-owner --username root_owner

# 2. Reset password for an administrator
freqid-admin reset-password --username john_admin

# 3. Unlock an account locked out due to failed logins
freqid-admin unlock --username john_admin

# 4. List all administrator accounts and lockout statuses
freqid-admin list-admins

# 5. Disable an administrator account immediately
freqid-admin disable-admin --username suspicious_admin
```

---

### 4. Admin Session & Cookie Security Architecture

Admin authentication uses **in-memory Bearer access tokens** combined with **rotating HttpOnly refresh cookies**:

- **Access Token**: Short-lived (15 minutes) signed JWT containing `sub` (admin UUID), `role`, and `permissions`. Kept strictly in frontend JavaScript memory (volatile RAM). Immune to CSRF on all API routes.
- **Refresh Cookie**: Long-lived (7 days) cryptographic token delivered via `Set-Cookie: refresh_token=...; HttpOnly; Secure; SameSite=Lax; Path=/v1/admin/auth`. Unreachable by JavaScript, preventing XSS exfiltration.
- **Session Family Rotation & Reuse Detection**: Every call to `POST /v1/admin/auth/refresh` revokes the old refresh token and issues a new one. If a revoked refresh token is reused (indicating token theft), the server revokes the entire token family, forcing re-authentication.
- **Anti-Enumeration Protection**: Login queries for non-existent usernames execute a baseline Argon2id calculation before returning `HTTP 401 INVALID_CREDENTIALS`, eliminating username enumeration side-channels.
- **Progressive Account & IP Lockouts**: 5 consecutive failed login attempts trigger an exponential lockout ($15\text{m} \to 30\text{m} \to 60\text{m}$) applied across both the username and client IP address.

---

## Complete API Surface (39 Endpoints)

### Biometric & Edge Device Endpoints
| Method | Path | Auth / Scope | Description |
|---|---|---|---|
| `GET` | `/healthz` | Public | Liveness probe |
| `GET` | `/readyz` | Public | Readiness probe (DB connection & model check) |
| `GET` | `/v1/model` | Public | Model metadata & checkpoint SHA-256 |
| `POST` | `/v1/verify` | Device Signature (`verify`) | 1:1 Biometric verification |
| `POST` | `/v1/identify` | Device Signature (`identify`) | 1:N Biometric search |
| `POST` | `/v1/enroll` | Device Signature (`enroll`) | Multi-sample template enrollment |
| `POST` | `/v1/devices/pair` | Single-use Token | Edge device pairing registration |
| `POST` | `/v1/devices/heartbeat`| Device Signature (`heartbeat`)| Device status and telemetry ping |

### Admin Authentication Endpoints (`/v1/admin/auth`)
| Method | Path | Auth / Scope | Description |
|---|---|---|---|
| `POST` | `/v1/admin/auth/login` | Public (Rate-limited)| Admin login, returns JWT + sets refresh cookie |
| `POST` | `/v1/admin/auth/refresh` | Refresh Cookie | Rotate refresh token and issue new access token |
| `POST` | `/v1/admin/auth/logout` | Bearer Token | Revoke refresh token and invalidate session |
| `GET` | `/v1/admin/auth/me` | Bearer Token | Current administrator profile and permissions |
| `POST` | `/v1/admin/auth/change-password` | Bearer Token | Self-service password change |
| `POST` | `/v1/admin/auth/mfa/setup` | Bearer Token | Provision TOTP secret and recovery codes |
| `POST` | `/v1/admin/auth/mfa/verify` | Bearer Token | Confirm TOTP activation |
| `POST` | `/v1/admin/auth/mfa/disable` | Bearer Token | Disable TOTP multi-factor authentication |

### Admin Device Management (`/v1/admin/devices`)
| Method | Path | Auth / Scope | Description |
|---|---|---|---|
| `GET` | `/v1/admin/devices` | `admin:devices:read` | List registered devices with filters and pagination |
| `POST` | `/v1/admin/devices/pairing-tokens` | `admin:devices:write` | Create single-use expiring pairing token |
| `GET` | `/v1/admin/devices/pairing-tokens` | `admin:devices:read` | List active pairing tokens |
| `DELETE` | `/v1/admin/devices/pairing-tokens/{id}`| `admin:devices:write`| Revoke pending pairing token |
| `GET` | `/v1/admin/devices/{id}` | `admin:devices:read` | Get detailed device info and telemetry |
| `PATCH` | `/v1/admin/devices/{id}` | `admin:devices:write` | Update device name or metadata |
| `POST` | `/v1/admin/devices/{id}/suspend` | `admin:devices:revoke`| Temporarily suspend device access |
| `POST` | `/v1/admin/devices/{id}/resume` | `admin:devices:revoke`| Resume active status of suspended device |
| `POST` | `/v1/admin/devices/{id}/revoke` | `admin:devices:revoke`| Permanently revoke device credentials |
| `DELETE` | `/v1/admin/devices/{id}` | `admin:devices:revoke`| Remove device record from database |

### Admin Identity Management (`/v1/admin/users` & `/v1/users`)
| Method | Path | Auth / Scope | Description |
|---|---|---|---|
| `GET` | `/v1/admin/users` | `admin:users:read` | Search and list enrolled identities |
| `GET` | `/v1/admin/users/{id}` | `admin:users:read` | Get user details and enrollment quality |
| `PATCH` | `/v1/admin/users/{id}` | `admin:users:write`| Update user metadata or external ID |
| `POST` | `/v1/users/{id}/disable` | `admin:users:write`| Disable user identity |
| `POST` | `/v1/users/{id}/enable` | `admin:users:write`| Enable user identity |
| `GET` | `/v1/users/{id}/export` | `admin:users:read` | GDPR Article 15 Data Subject Access Request export |
| `DELETE` | `/v1/users/{id}` | `admin:users:delete`| GDPR Article 17 Right to Erasure complete deletion |
| `GET` | `/v1/migrations/report` | `admin:users:read` | Model version distribution report |

### Admin System & Audit Management (`/v1/admin/system` & `/v1/admin/admins`)
| Method | Path | Auth / Scope | Description |
|---|---|---|---|
| `GET` | `/v1/admin/admins` | `admin:admins:read` | List administrator accounts |
| `POST` | `/v1/admin/admins` | `admin:admins:write`| Create new administrator (`admin`, `operator`, `auditor`) |
| `PATCH` | `/v1/admin/admins/{id}` | `admin:admins:write`| Update administrator role or status |
| `DELETE` | `/v1/admin/admins/{id}` | `admin:admins:owner`| Delete administrator account |
| `GET` | `/v1/admin/system/status` | `system:read` | Database pool, vector index, and host metrics |
| `GET` | `/v1/admin/system/settings` | `system:read` | View configurable system settings |
| `PATCH` | `/v1/admin/system/settings` | `system:write`| Update system settings |
| `GET` | `/v1/admin/system/audit` | `audit:read` | Query structured audit events |
| `GET` | `/v1/admin/system/audit/export` | `audit:export_csv` | Stream tamper-evident audit records to CSV |

---

## Empirical Benchmarks & Performance

All benchmarks measured on Linux with AMD Ryzen 7 5700X 8-Core Processor:

### 1. Authentication & Signing Latency
- **Client Ed25519 Signing Latency**: **p50 = 0.231 ms**, **p95 = 0.354 ms** (sub-millisecond overhead).
- **Server Signature Verification & Nonce Validation**: **< 0.150 ms**.
- **Sequential 1:1 Verify (Client SDK -> Live Uvicorn -> PostgreSQL + Audit)**:
  - **Median (p50)**: **54.55 ms**
  - **95th Percentile (p95)**: **76.50 ms**

### 2. High Concurrency Throughput (Live Edge Signature Verification)
- **Concurrent Load ($c = 8$ concurrent client workers)**:
  - Success Rate: **100% (8/8)**
  - Median Latency: **377.12 ms**
  - 95th Percentile: **429.18 ms**
  - Throughput: **18.4 req/s**
- **Concurrent Load ($c = 32$ concurrent client workers)**:
  - Success Rate: **100% (32/32)**
  - Median Latency: **1570.41 ms**
  - 95th Percentile: **1644.46 ms**
  - Throughput: **19.3 req/s**

### 3. Envelope Encryption & Key Rotation
- **Throughput**: **7,443.8 records/second** (1,000 records rotated in 134.34 ms).
- **Integrity**: 100% byte-for-byte unmodified biometric ciphertext verification.

---

## Testing & Quality Assurance

```bash
# Run backend test suite (62 tests, 100% pass)
pytest backend/tests/ -v

# Run full project test suite across all packages (116 tests, 100% pass)
pytest backend/tests/ client-sdk/tests/ core/tests/
```

