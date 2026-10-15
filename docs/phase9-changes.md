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
