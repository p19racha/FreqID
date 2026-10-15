# Phase 5 Changes & Adaptations to Phase 4 Codebase

This document details all modifications and extensions made to the Phase 4 codebase during Phase 5 (Persistent Storage & Enrollment Lifecycle). In accordance with Hard Rule 1, changes to `freqid_server` were strictly confined to persistence, encryption, audit, and lifecycle wiring. Upstream TFace, `freqid_core`, and `freqid_client` remain untouched.

---

## 1. Upstream & Sibling Packages (Hard Rule Invariant)

- **`recognition/` (Upstream Tencent/TFace)**: **ZERO modifications.** No files added, modified, or deleted.
- **`core/` (`freqid_core`)**: **ZERO modifications.** Binary payload format, transform math, IR-18 model definition, ONNX export, and cosine matching remain byte-for-byte identical to Phase 2.
- **`client-sdk/` (`freqid_client`)**: **ZERO modifications.** Face detection, landmark alignment, capture pipelines, and transport logic remain identical to Phase 3. Real client SDK E2E tests pass against the persistent PostgreSQL server.

---

## 2. Server Configuration (`backend/src/freqid_server/config.py`)

Added typed settings fields using Pydantic Settings:
- **Persistence Settings**:
  - `store_backend: Literal["memory", "postgres"]` (default `"postgres"`).
  - `database_url: str` (defaults to asyncpg connection string).
  - `database_pool_size: int` (default `20`).
  - `database_max_overflow: int` (default `10`).
  - `database_echo: bool` (default `False`, enforced to prevent parameter logging).
- **Cryptographic Key Provider Settings**:
  - `active_key_version: int` (default `1`).
  - `master_keys: Dict[int, str]` (loaded from `FREQID_MASTER_KEY_V<N>` environment variables).
  - `key_dir: Optional[Path]` (optional directory for file-based POSIX `0600` keys).
- **Audit Logging Subsystem Settings**:
  - `audit_enabled: bool` (default `True`).
  - `audit_batch_size: int` (default `50`).
  - `audit_flush_interval: float` (default `1.0` second).
  - `audit_queue_capacity: int` (default `10000`).
  - `audit_tamper_evident: bool` (default `False`, enables SHA-256 hash chaining).
- **Enrollment Duplicate Detection Settings**:
  - `enroll_duplicate_check: bool` (default `True`).
  - `enroll_duplicate_threshold: float` (default `0.65`).
  - `enroll_duplicate_policy: Literal["warn", "block"]` (default `"block"`).

---

## 3. Storage Interface & Models (`backend/src/freqid_server/storage/`)

### Abstract Interface (`base.py`)
- Extended `StoredTemplate` dataclass with `optimistic_version: int = 1`.
- Extended `TemplateStore` ABC with identity lifecycle methods:
  - `enable_user(user_id: str) -> None`
  - `disable_user(user_id: str) -> None`
  - `get_user_audit_history(user_id: str, limit: int = 50) -> List[Dict[str, Any]]`
  - `get_model_version_distribution() -> Dict[str, int]`

### In-Memory Test Double (`memory.py`)
- Updated `MemoryTemplateStore` to maintain `optimistic_version` state per template, incrementing monotonically on updates to ensure 100% contract test suite parity with `PostgreSQLTemplateStore`.
- Implemented `enable_user`, `disable_user`, `get_user_audit_history`, and `get_model_version_distribution` in memory.

### ORM Models (`models.py`)
- Added SQLAlchemy 2.0 declarative mappings:
  - `User`: Primary key UUID, `external_id` (unique index), `is_active`, `created_at`, `updated_at`.
  - `Template`: Primary key UUID, foreign key to `users.id` with `ON DELETE CASCADE`, `model_version`, `embedding_encrypted` (`LargeBinary`), `wrapped_dek` (`LargeBinary`), `dek_nonce` (`LargeBinary`), `data_nonce` (`LargeBinary`), `key_version` (`Integer`), `optimistic_version` (`Integer`), `quality_score`, `sample_count`.
  - `AuditEvent`: Primary key `BigInteger` (autoincrement), `event_id` (UUID), `timestamp`, `event_type`, `user_id` (foreign key to `users.id` with `ON DELETE SET NULL`), `client_ip_hash`, `device_id`, `decision`, `coarse_score_bucket`, `prev_hash`, `current_hash`.

### PostgreSQL Implementation (`postgres.py`)
- Implemented `PostgreSQLTemplateStore` utilizing asyncpg connection pooling.
- Streaming keyset pagination for bulk gallery ingestion to prevent high-watermark memory spikes.
- Envelope encryption integration: delegates encryption to `TemplateEncryptor` before database writes, and decryption upon database reads.
- Optimistic concurrency control: updates check `WHERE optimistic_version = :expected_version`, raising `OptimisticLockError` on concurrent mutations.

---

## 4. API Endpoints & Routes (`backend/src/freqid_server/api/`)

### 1:1 Verification (`routes_verify.py`) & 1:N Identification (`routes_identify.py`)
- Integrated non-blocking audit logging via `app.state.audit_sink.record(...)`.
- Added user status check: if `user.is_active is False`, verification immediately halts with `HTTP 403 Forbidden` (`ACCOUNT_DISABLED`).
- Anonymized client IP addresses using SHA-256 hashing with salt before passing to the audit sink.
- Masked raw cosine similarity scores into coarse categorical buckets (`"very_high"`, `"high"`, `"medium"`, `"low"`, `"very_low"`) for non-admin audit records.

### Enrollment & Lifecycle (`routes_enroll.py`)
- **Duplicate Template Detection**: Evaluates newly synthesized embedding against existing gallery using `matching_service.identify(...)`. If similarity exceeds threshold and policy is `"block"`, raises `HTTP 409 Conflict` (`DUPLICATE_IDENTITY`).
- **Re-Enrollment Safeguard**: If `external_id` already exists, requires explicit `X-Re-Enroll: true` HTTP header to prevent inadvertent template overwriting.
- **Account State Routes**: Added `POST /v1/users/{id}/disable` and `POST /v1/users/{id}/enable`.
- **GDPR Subject Access Request (Article 15)**: Added `GET /v1/users/{id}/export`, returning user metadata, template quality, and redacted audit history.
- **GDPR Right to Erasure (Article 17)**: Updated `DELETE /v1/users/{id}` to execute complete deletion of identity and templates, leveraging PostgreSQL's `ON DELETE SET NULL` cascade to anonymize audit log rows without violating the append-only constraint.
- **Model Version Migration Report**: Added `GET /v1/migrations/report` endpoint returning template counts partitioned by `model_version`.

---

## 5. Errors & Services (`backend/src/freqid_server/errors.py`, `services/`)

- **`errors.py`**: Added `DuplicateIdentityError` mapped to `HTTP 409 Conflict`.
- **`services/gallery.py`**: Added `.identities` property exposing the set of unique user external identifiers stored in the active gallery snapshot.
- **`services/enrollment.py`**: Added `pack_framed_payloads(...)` helper for bundling individual payloads into a streamable byte format for enrollment tests.

---

## 6. Application Lifecycle & Dependency Injection (`backend/src/freqid_server/main.py`)

- **FastAPI Lifespan Context Manager**:
  - Automatically provisions the SQLAlchemy async engine and connection pool when `FREQID_STORE_BACKEND="postgres"`.
  - Initializes `EnvOrFileKeyProvider` and `TemplateEncryptor`.
  - Starts the background `PostgresAuditSink` worker thread/task.
  - On application shutdown: drains the audit queue, cancels workers, and cleanly disposes of the connection pool (`engine.dispose()`).
