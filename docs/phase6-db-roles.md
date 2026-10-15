# PostgreSQL Database Roles and Least-Privilege Access Control (Phase 6)

This document defines the database role architecture, permission matrices, and initialization scripts for **FreqID** Phase 6 (Identity, Device Network, Admin Accounts).

---

## 1. Role Architecture & Principle of Least Privilege

FreqID enforces separation of duties across three dedicated database roles:

1. **`freqid_admin` (Migration & Schema Owner)**:
   - Used **exclusively** during schema migrations (`alembic upgrade`).
   - Owns all tables, constraints, foreign keys, and sequences in schema `public`.
   - Never used by the runtime application server or edge clients.
2. **`freqid_app` (Application Runtime)**:
   - Used by the running `freqid-server` FastAPI process.
   - **Allowed**: `SELECT, INSERT, UPDATE, DELETE` on:
     - `users`, `templates`, `enrollment_sessions`
     - `admin_users`, `admin_refresh_tokens`
     - `devices`, `pairing_tokens`
   - **Allowed**: `SELECT, INSERT` on:
     - `audit_events`
     - `device_heartbeats`
   - **Allowed**: `SELECT, UPDATE` on `system_settings`.
   - **Strictly Denied**: `UPDATE`, `DELETE`, `TRUNCATE` on `audit_events` (enforces an immutable, append-only audit trail at the engine level).
   - **Strictly Denied**: `CREATE`, `DROP`, `ALTER` on any schema or table.
3. **`freqid_maint` (Maintenance & Retention)**:
   - Used by background maintenance jobs (`audit_retention.py`, `device_retention.py`).
   - **Allowed**: `SELECT, DELETE` on `audit_events` (older than configured retention threshold).
   - **Allowed**: `SELECT, DELETE` on `device_heartbeats` (older than heartbeat retention threshold).
   - **Allowed**: `SELECT, DELETE` on `pairing_tokens` (expired and burned tokens).
   - **Strictly Denied**: Access to biometric templates (`templates`), users (`users`), or admin credentials (`admin_users`).

---

## 2. Permission Matrix

| Table | `freqid_admin` | `freqid_app` (Runtime Server) | `freqid_maint` (Maintenance) |
|---|:---:|:---:|:---:|
| `users` | ALL | SELECT, INSERT, UPDATE, DELETE | None |
| `templates` | ALL | SELECT, INSERT, UPDATE, DELETE | None |
| `enrollment_sessions` | ALL | SELECT, INSERT, UPDATE, DELETE | None |
| `admin_users` | ALL | SELECT, INSERT, UPDATE, DELETE | None |
| `admin_refresh_tokens` | ALL | SELECT, INSERT, UPDATE, DELETE | None |
| `devices` | ALL | SELECT, INSERT, UPDATE, DELETE | None |
| `pairing_tokens` | ALL | SELECT, INSERT, UPDATE, DELETE | SELECT, DELETE |
| `device_heartbeats` | ALL | SELECT, INSERT | SELECT, DELETE |
| `system_settings` | ALL | SELECT, UPDATE | None |
| `audit_events` | ALL | **INSERT, SELECT** (NO UPDATE/DELETE) | **SELECT, DELETE** |
| `alembic_version` | ALL | SELECT | None |
| Sequences (`*_seq`) | ALL | USAGE, SELECT | USAGE, SELECT |

---

## 3. SQL Role Provisioning Script

The following SQL script applies these privileges to the PostgreSQL database:

```sql
-- Connect to database as superuser or admin
\c freqid;

-- 1. Grant schema usage
GRANT USAGE ON SCHEMA public TO freqid_app;
GRANT USAGE ON SCHEMA public TO freqid_maint;

-- 2. Grant table privileges to freqid_app
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE users TO freqid_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE templates TO freqid_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE enrollment_sessions TO freqid_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE admin_users TO freqid_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE admin_refresh_tokens TO freqid_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE devices TO freqid_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE pairing_tokens TO freqid_app;
GRANT SELECT, INSERT ON TABLE device_heartbeats TO freqid_app;
GRANT SELECT, UPDATE ON TABLE system_settings TO freqid_app;
GRANT SELECT, INSERT ON TABLE audit_events TO freqid_app;
GRANT SELECT ON TABLE alembic_version TO freqid_app;

-- Grant sequence permissions
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO freqid_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO freqid_maint;

-- 3. Strict Append-Only Invariant: Deny modification of audit logs
REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_events FROM freqid_app;

-- 4. Grant maintenance retention permissions to freqid_maint
GRANT SELECT, DELETE ON TABLE audit_events TO freqid_maint;
GRANT SELECT, DELETE ON TABLE device_heartbeats TO freqid_maint;
GRANT SELECT, DELETE ON TABLE pairing_tokens TO freqid_maint;

-- 5. Set default privileges for future tables created by freqid_admin
ALTER DEFAULT PRIVILEGES FOR ROLE freqid_admin IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO freqid_app;

ALTER DEFAULT PRIVILEGES FOR ROLE freqid_admin IN SCHEMA public
    REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_events FROM freqid_app;
```
