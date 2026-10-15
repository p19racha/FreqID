# FreqID Operations & Incident Response Runbook

This operational runbook provides standard operating procedures (SOPs) and emergency incident response playbooks for the **FreqID** privacy-preserving facial recognition system.

---

## 1. Edge Device Lifecycle & Incident Response

### 1.1 Device Pairing Procedure (Normal Operation)
When commissioning a new edge camera, kiosk, or access terminal:

1. **Issue Pairing Token (Admin)**:
   An administrator with `admin:devices:write` permissions generates a single-use token:
   ```bash
   curl -X POST http://127.0.0.1:8000/v1/admin/devices/pairing-tokens \
     -H "Authorization: Bearer <ADMIN_ACCESS_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"name": "bldg-a-gate-01", "expires_in_minutes": 15}'
   ```
   *Expected Response*: `{"token": "<32-char-hex-token>", "expires_at": "...", "token_id": "..."}`

2. **Execute On-Device Pairing (Edge Technician)**:
   On the physical edge device running `freqid-client`:
   ```bash
   freqid-client pair \
     --server http://127.0.0.1:8000 \
     --token "<32-char-hex-token>" \
     --name "bldg-a-gate-01" \
     --credentials ~/.freqid/device_credentials.json
   ```
   *Verification*:
   - Confirm output displays `[SUCCESS] Device successfully paired`.
   - Confirm credentials file has strict POSIX permissions:
     ```bash
     ls -l ~/.freqid/device_credentials.json
     # Must display: -rw------- (0600)
     ```

3. **Verify Connectivity & Health**:
   ```bash
   freqid-client status --credentials ~/.freqid/device_credentials.json
   ```

---

### 1.2 Incident Playbook: Lost or Stolen Edge Device
**Severity**: High  
**Objective**: Terminate device network access immediately ($0\text{ ms}$ delay) and analyze potential exposure.

1. **Step 1: Immediate Server-Side Revocation**:
   Execute instant revocation via the Admin API:
   ```bash
   curl -X POST http://127.0.0.1:8000/v1/admin/devices/<DEVICE_UUID>/revoke \
     -H "Authorization: Bearer <ADMIN_ACCESS_TOKEN>"
   ```
   *Result*: The device record status transitions to `revoked` in PostgreSQL. All subsequent verification or identification requests signed by this device are rejected with `HTTP 401 DEVICE_REVOKED` instantly.

2. **Step 2: Verify Revocation**:
   Query device details:
   ```bash
   curl -X GET http://127.0.0.1:8000/v1/admin/devices/<DEVICE_UUID> \
     -H "Authorization: Bearer <ADMIN_ACCESS_TOKEN>"
   ```
   Confirm `"state": "revoked"`.

3. **Step 3: Forensic Audit Investigation**:
   Extract all activity logs for this device to determine if unauthorized access was attempted:
   ```bash
   curl -X GET "http://127.0.0.1:8000/v1/admin/system/audit?device_id=<DEVICE_UUID>&limit=100" \
     -H "Authorization: Bearer <ADMIN_ACCESS_TOKEN>"
   ```
   *Privacy Assurance*:
   - The edge device stores **zero biometric templates, zero gallery embeddings, and zero raw facial images**.
   - A stolen device contains only its private signing key and client software. Even if the device's storage is extracted, an attacker cannot retrieve facial identities or biometric data.

4. **Step 4: Cleanup & Deletion**:
   Once audit analysis is concluded, remove the device record from the registry if decommissioned:
   ```bash
   curl -X DELETE http://127.0.0.1:8000/v1/admin/devices/<DEVICE_UUID> \
     -H "Authorization: Bearer <ADMIN_ACCESS_TOKEN>"
   ```

---

### 1.3 Incident Playbook: Compromised Device Private Key
**Severity**: Critical  
**Objective**: Revoke key, invalidate active pairing, and provision a new keypair.

1. **Revoke the Compromised Device**:
   ```bash
   curl -X POST http://127.0.0.1:8000/v1/admin/devices/<DEVICE_UUID>/revoke \
     -H "Authorization: Bearer <ADMIN_ACCESS_TOKEN>"
   ```

2. **Purge Compromised Credentials on Edge Hardware**:
   ```bash
   # Securely shred local credential file
   shred -u ~/.freqid/device_credentials.json
   ```

3. **Re-Pair Hardware with Fresh Cryptographic Identity**:
   - Issue a new pairing token from the Admin API.
   - Run `freqid-client pair` with the new token.
   - A fresh Ed25519 keypair is generated locally. The old public key is permanently disabled.

---

## 2. Administrator Account & Session Security

### 2.1 Incident Playbook: Compromised Administrator Account
**Severity**: Critical  
**Objective**: Sever active sessions, reset authentication factors, and audit actions taken.

1. **Step 1: Instantly Disable the Account**:
   Using the `freqid-admin` CLI on the host server:
   ```bash
   freqid-admin disable-admin --username <COMPROMISED_USERNAME>
   ```
   *Result*: The account `is_active` flag is set to `False`. The server's `UnifiedAuthenticator` rejects all incoming bearer tokens for disabled administrators on the next request.

2. **Step 2: Emergency Password Reset**:
   ```bash
   freqid-admin reset-password --username <COMPROMISED_USERNAME>
   ```
   Enter a new, cryptographically strong password (minimum 12 characters).

3. **Step 3: Invalidate All Active Refresh Sessions**:
   Disabling or updating the account revokes active token families in `admin_refresh_tokens`.
   To verify in PostgreSQL:
   ```sql
   UPDATE admin_refresh_tokens 
   SET is_revoked = TRUE 
   WHERE admin_id = (SELECT id FROM admin_users WHERE username = '<COMPROMISED_USERNAME>');
   ```

4. **Step 4: Audit Forensic Reconstruction**:
   Export all audit records generated by the administrator during the compromise window:
   ```bash
   curl -X GET "http://127.0.0.1:8000/v1/admin/system/audit?admin_id=<ADMIN_UUID>&limit=500" \
     -H "Authorization: Bearer <OWNER_ACCESS_TOKEN>"
   ```
   Review created pairing tokens, modified user identities, and exported records.

---

### 2.2 Operational Playbook: Progressive Account Lockout Unlocking
**Severity**: Low / Routine  
**Condition**: An administrator entered incorrect passwords 5 or more times, triggering automated progressive lockout ($15\text{m} \to 30\text{m} \to 60\text{m}$).

1. **Inspect Lockout Status**:
   ```bash
   freqid-admin list-admins
   ```
   Locate the account in the output table and inspect the `Locked Until` column.

2. **Clear Lockout & Reset Counters**:
   ```bash
   freqid-admin unlock --username <LOCKED_USERNAME>
   ```
   *Expected Output*: `Success: Account '<LOCKED_USERNAME>' unlocked.`
   The administrator may now log in immediately.

---

## 3. Cryptographic Key Management & Envelope Rotation

### 3.1 Playbook: Master Key (`KEK`) Rotation
**Objective**: Rotate the system's AES-256 master key across all enrolled biometric templates.  
FreqID utilizes envelope encryption. Re-wrapping requires only decrypting the 32-byte Data Encryption Key (DEK) with the old master key and re-encrypting it with the new master key. The biometric ciphertext ($2,048\text{ bytes}$) is never modified or exposed in plaintext.

1. **Generate New 256-bit Master Key**:
   ```bash
   openssl rand -hex 32
   # Output: e.g. 9f8a3c... (64 hex characters)
   ```

2. **Configure Environment Variables**:
   Update `/etc/freqid/server.env` or systemd service environment:
   ```bash
   # Retain existing keys for decryption
   export FREQID_MASTER_KEY_V1="<EXISTING_HEX_KEY>"
   
   # Add new master key version
   export FREQID_MASTER_KEY_V2="<NEW_HEX_KEY>"
   
   # Set active version to the new version for new enrollments
   export FREQID_ACTIVE_KEY_VERSION=2
   ```

3. **Execute Online Re-wrapping Script**:
   Run the high-performance rotation utility:
   ```bash
   python backend/scripts/rotate_keys.py \
     --database-url "postgresql+asyncpg://freqid_app:secret@127.0.0.1:54322/freqid" \
     --new-version 2 \
     --batch-size 500
   ```
   *Empirical Performance*: Rotates at **~7,440 records/second**. A gallery of 50,000 users re-wraps in under 7 seconds.

4. **Verify Ciphertext & Template Parity**:
   Run the verification check to ensure all templates decrypt cleanly under Key Version 2:
   ```bash
   pytest backend/tests/test_encryption.py -v
   ```

---

## 4. Audit Trail Verification & Compliance

### 4.1 Playbook: Tamper-Evident Audit Chain Verification
**Objective**: Cryptographically verify that historical audit records have not been altered, injected, or removed.

1. **Run Cryptographic Verification**:
   ```bash
   python backend/scripts/verify_audit_chain.py \
     --database-url "postgresql+asyncpg://freqid_app:secret@127.0.0.1:54322/freqid"
   ```
   *Expected Output*: `[PASS] Audit chain verified. All 14,280 events mathematically intact.`

2. **Export Audit Trail to CSV for Compliance Review**:
   ```bash
   curl -X GET "http://127.0.0.1:8000/v1/admin/system/audit/export?format=csv" \
     -H "Authorization: Bearer <AUDITOR_ACCESS_TOKEN>" \
     -o audit_export_$(date +%Y%m%d).csv
   ```

---

## 5. Routine System Maintenance & Health Checks

### 5.1 Service Health Probes
```bash
# 1. Liveness Probe
curl -f http://127.0.0.1:8000/healthz

# 2. Readiness Probe (validates PostgreSQL pool and ONNX inference engine)
curl -f http://127.0.0.1:8000/readyz

# 3. Model Metadata & Checksum
curl -s http://127.0.0.1:8000/v1/model | jq .
```

### 5.2 Expired Token & Telemetry Retention Pruning
Run the maintenance retention script via cron using the restricted `freqid_maint` database role:
```bash
# Clear audit events older than 90 days and expired pairing tokens
python backend/scripts/audit_retention.py \
  --database-url "postgresql+asyncpg://freqid_maint:secret@127.0.0.1:54322/freqid" \
  --retention-days 90 \
  --batch-size 1000
```
