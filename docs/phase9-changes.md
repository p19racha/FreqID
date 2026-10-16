# FreqID Phase 9 Changes Log

In accordance with Hard Rule 3, all modifications to `freqid_core`, `freqid_client`, `freqid_server`, and `admin-ui` during Phase 9 are documented in this file with justification, affected files, and verification procedures.

---

## 1. Non-Root System User UID/GID Alignment

- **Component**: `backend/Dockerfile`, `deploy/docker-compose.yml`
- **Rationale**: When mounting secrets with mode `0600` from the host filesystem into unprivileged containers running as non-root, Docker on Linux preserves host ownership (UID 1000). Setting the non-root `freqid` system user UID/GID to 1000 (with runtime environment overrides `${FREQID_UID:-1000}:${FREQID_GID:-1000}`) allows the unprivileged server process to read host-mounted `0600` secret files without requiring root privileges or file mode relaxation.
- **Verification**: Verified non-root execution via `docker run --rm --entrypoint id freqid/server:0.1.0` (`uid=1000(freqid) gid=1000(freqid)`). Confirmed `master.key` (mode 0600) is successfully loaded and validated by `EnvOrFileKeyProvider`.

---

## 2. Prometheus Observability Metrics Endpoint (`/metrics`)

- **Component**: `backend/src/freqid_server/api/routes_health.py`, `deploy/Caddyfile`
- **Rationale**: Phase 9 Step 5 requires system observability with health and operational metrics. Adding `/metrics` in Prometheus text exposition format provides standard monitoring metrics (`freqid_up`, `freqid_store_connected`, `freqid_model_loaded`, `freqid_enrolled_identities`) without adding any external dependencies.
- **Verification**: Tested via `curl http://localhost:8088/metrics` through Caddy reverse proxy, confirming HTTP 200 and standard Prometheus exposition format.

---

## 3. Alembic Downgrade / Upgrade Foreign Key Constraint Handling

- **Component**: `backend/alembic/versions/a1b2c3d4e5f6_phase6_admin_and_devices.py`
- **Rationale**: When rolling back from Phase 6 (`a1b2c3d4e5f6`) to Phase 4 (`f4e3d2c1b0a9`) and re-applying `upgrade head`, orphan UUID values in `audit_events.device_id` and `enrollment_sessions.device_id` (pointing to dropped device records) caused foreign key constraint creation failures. Executing cleanup updates to nullify orphan references before recreating foreign key constraints ensures clean, non-destructive migration rollbacks and re-upgrades.
- **Verification**: Verified via `docker compose run --rm migrate downgrade -1` followed by `docker compose run --rm migrate upgrade head`. Both completed with zero errors and schema integrity was preserved.

---

## 4. Docker Compose Migration Container Entrypoint / Command Separation

- **Component**: `deploy/docker-compose.yml`
- **Rationale**: Combining `entrypoint: ["alembic", "upgrade", "head"]` prevented passing CLI arguments (such as `downgrade -1` or `current`) when using `docker compose run --rm migrate <cmd>`. Separating into `entrypoint: ["alembic"]` and `command: ["upgrade", "head"]` retains the default behavior while supporting operational migration commands.
- **Verification**: Verified running `alembic current` and `alembic downgrade -1` without argument collision.

---

## 5. Caddy Ingress Edge API Route Matcher

- **Component**: `deploy/Caddyfile`, `deploy/docker-compose.yml`, `deploy/.env.example`
- **Rationale**: The edge `client-sdk` issues requests to `/api/v1/*` endpoints (`/api/v1/auth/verify`, `/api/v1/enroll/frames`, etc.). The original `@api_routes` matcher in Caddy only captured `/v1/*`, causing edge requests to fall through to `admin-ui:8080` (nginx), which returned HTTP 413. Expanding `@api_routes` to include `path /api/*` properly proxies all client-sdk requests to FastAPI. Additionally, `FREQID_SERVER_AUDIT_ENABLE_HASH_CHAIN=true` was enabled in compose and .env.example to ensure cryptographic audit hash chaining is active in production.
- **Verification**: Verified via simulated client-sdk enrollment and verification over Caddy reverse proxy (`http://localhost:8088`).

