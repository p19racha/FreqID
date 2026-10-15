# PostgreSQL Database Roles and Least-Privilege Access Control

This document defines the database role architecture, permission matrices, and initialization scripts for **FreqID** Phase 5.

---

## 1. Role Architecture & Principle of Least Privilege

FreqID separates database access into distinct roles to enforce security invariants at the database engine level:

1. **`freqid_admin` (Migration & Schema Owner)**:
   - Used **only** during schema migrations (`alembic upgrade`).
   - Owns the database tables and sequences.
   - Never used by the runtime application server.
2. **`freqid_app` (Application Runtime)**:
   - Used by the running `freqid-server` process.
   - **Allowed**: `SELECT, INSERT, UPDATE, DELETE` on `users`, `templates`, and `enrollment_sessions`.
   - **Allowed**: `INSERT, SELECT` on `audit_events`.
   - **Strictly Denied**: `UPDATE` and `DELETE` on `audit_events` (enforces append-only audit trail).
   - **Strictly Denied**: `CREATE`, `DROP`, `ALTER` on any schema or table.
3. **`freqid_maint` (Maintenance & Retention)**:
   - Used by offline background maintenance jobs (e.g. `scripts/audit_retention.py`).
   - **Allowed**: `SELECT, DELETE` on `audit_events` for pruning events older than the retention threshold.
   - Cannot modify biometric templates or user records.

---

## 2. Permission Matrix

| Table | `freqid_admin` | `freqid_app` (Server) | `freqid_maint` (Retention) |
|---|---|---|---|
| `users` | ALL | SELECT, INSERT, UPDATE, DELETE | None |
| `templates` | ALL | SELECT, INSERT, UPDATE, DELETE | None |
| `enrollment_sessions` | ALL | SELECT, INSERT, UPDATE, DELETE | None |
| `audit_events` | ALL | **INSERT, SELECT** (NO UPDATE/DELETE) | **SELECT, DELETE** |
| `alembic_version` | ALL | SELECT | None |

---

## 3. SQL Initialization Script

The following script is executed during container initialization or cluster provisioning:

```sql
-- 1. Create Application and Maintenance Roles
CREATE USER freqid_app WITH PASSWORD 'freqid_app_dev_secret';
CREATE USER freqid_maint WITH PASSWORD 'freqid_maint_dev_secret';

-- 2. Connect to the freqid database
\c freqid;

-- 3. Grant schema usage
GRANT USAGE ON SCHEMA public TO freqid_app;
GRANT USAGE ON SCHEMA public TO freqid_maint;

-- 4. Grant table privileges to freqid_app
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE users TO freqid_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE templates TO freqid_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE enrollment_sessions TO freqid_app;
GRANT SELECT, INSERT ON TABLE audit_events TO freqid_app;
GRANT SELECT ON TABLE alembic_version TO freqid_app;

-- Ensure sequences can be used for IDs if applicable
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO freqid_app;

-- 5. Revoke destructive privileges on audit_events for application role
REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_events FROM freqid_app;

-- 6. Grant maintenance retention privileges to freqid_maint
GRANT SELECT, DELETE ON TABLE audit_events TO freqid_maint;

-- 7. Ensure future tables created by migrations inherit permissions
ALTER DEFAULT PRIVILEGES FOR ROLE freqid_admin IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO freqid_app;

ALTER DEFAULT PRIVILEGES FOR ROLE freqid_admin IN SCHEMA public
    REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_events FROM freqid_app;
```
