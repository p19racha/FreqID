# FreqID Administrator & Compliance Guide

Welcome to the **FreqID Administrative Dashboard**. This guide is designed for system administrators, fleet operators, and Data Protection Officers (DPOs) responsible for managing privacy-preserving face recognition fleets and ensuring compliance with data privacy regulations (such as GDPR).

---

## 1. Architectural & Privacy Model Overview

FreqID is engineered around the principle of **Zero Spatial Exposure**:
- **Zero Facial Images in the Browser**: The administration dashboard runs entirely in standard web browsers and **never** accesses cameras, requests video streams, or handles raw face photos.
- **Physical Isolation of Biometric Enrollment**: All enrollment and face recognition happen exclusively on paired physical edge devices (e.g., turnstiles, kiosks, access control units) running `freqid-client`. Edge devices convert spatial camera frames into 27-channel DCT partial-frequency representations on device, transmitting only partial-frequency payloads to `freqid-server`.
- **In-Memory Volatile Session Security**: Administrative credentials and tokens are held only in temporary browser memory. When you log out, close the tab, or remain inactive, all session tokens are wiped immediately. No credentials or biometrics are ever stored in browser cookies or persistent storage.

---

## 2. Managing the Edge Device Fleet

Physical devices running `freqid-client` require explicit administrative authorization before they can process verifications or communicate with the server.

### 2.1 Pairing a New Edge Device

To onboard a new edge camera or turnstile unit:
1. Navigate to **Devices** in the sidebar.
2. Click the **Add Device** button in the top right.
3. Enter a descriptive **Device Name** (e.g., `lobby-turnstile-east-01`).
4. Select the allowed operational scope:
   - `verify` (Default): Allows 1:1 face verification only.
   - `identify`: Allows 1:N open search matching.
   - `enroll`: Authorizes the device to capture and enroll new identities.
5. Choose a pairing token expiration window (e.g., 15 minutes).
6. Click **Generate Pairing Token**.
7. The screen displays a 128-bit pairing token **exactly once**.
   > **Important Security Notice**: This secret token is shown once and cannot be retrieved again after closing the dialog. Copy the pairing token or the generated CLI command immediately:
   > ```bash
   > freqid-client pair --server "https://freqid.internal" --token "<token>" --name "lobby-turnstile-east-01"
   > ```
8. Execute the command on the edge device. The dialog will monitor the network and transition to **Pairing Complete** automatically once the hardware key exchange succeeds.

### 2.2 Device Lifecycle States & Monitoring

The device registry shows real-time operational status for each edge unit:
- <span style="color:#10b981;font-weight:bold;">Active</span>: The device is cryptographically authenticated and actively processing inference requests.
- <span style="color:#f59e0b;font-weight:bold;">Pending</span>: The device has registered its public key and is awaiting administrative activation.
- <span style="color:#ea580c;font-weight:bold;">Suspended</span>: The device's credentials are temporarily paused. Verification requests will return `401 Unauthorized` until resumed.
- <span style="color:#e11d48;font-weight:bold;">Revoked</span>: The device's Ed25519 public key has been permanently blacklisted. It can never authenticate again.

### 2.3 Suspending vs. Revoking an Edge Device

- **Temporary Suspension**: If a camera unit is undergoing physical maintenance or suspected of intermittent tampering, open the device details and click **Suspend Device**. This takes effect with **$0\text{ ms}$ propagation delay** without deleting historical audit telemetry. Click **Resume Device** when maintenance completes.
- **Permanent Revocation**: If a device is stolen, decommissioned, or physically compromised, click **Revoke Device**. To prevent accidental outages on critical physical security infrastructure, the dashboard requires you to **type the exact device name** before confirming revocation. Revocation is atomic and irreversible.

---

## 3. Identity Registry & GDPR Data Subject Rights

FreqID provides end-to-end support for privacy compliance and the European Union General Data Protection Regulation (GDPR).

### 3.1 GDPR Article 15: Right of Access (Data Export)

Enrolled individuals have the legal right to inspect all personal metadata and biometric tracking information stored about them.
1. Navigate to **Users** in the sidebar.
2. Search for the individual by internal UUID or External System ID (e.g., employee badge number).
3. Click on the user to open their profile.
4. Click **Export Data (GDPR Art. 15)**.
5. The portal immediately downloads a standardized, machine-readable JSON archive containing:
   - Unique Subject Identifier and creation timestamp.
   - Active account status.
   - Associated biometric template count, vector dimensions ($512$), and neural network model version.
   - Complete historical audit event timeline.

### 3.2 GDPR Article 17: Right to Erasure ("Right to be Forgotten")

When an employee departs or a user revokes consent, their biometric template must be irreversibly destroyed.
1. Open the user profile in **Users**.
2. **Step 1 (Recommended Soft Disable)**: Click **Disable Identity**. This immediately halts all physical access verifications while keeping records available for compliance validation.
3. **Step 2 (Permanent Cascade Deletion)**: Click **Delete Identity (GDPR Art. 17)**.
4. Review the confirmation dialog. Deleting the user permanently purges:
   - The user record and database references.
   - All encrypted biometric vector templates in PostgreSQL.
   - The in-memory vector similarity index.
5. An immutable audit record recording the deletion event (with admin ID and timestamp) is preserved for regulatory defense.

### 3.3 Neural Network Re-Enrollment Workflow

When FreqID is upgraded to a newer neural network model (e.g., transitioning from `partialface_ir18_v1` to a newer backbone), existing biometric vector templates cannot be compared across model architectures.
1. Navigate to **Users** and click **Re-Enrollment Report**.
2. The report identifies all registered identities whose stored templates were generated by legacy model versions.
3. Use the CSV export button to notify affected departments or schedule re-enrollment appointments at designated enrollment kiosks.

---

## 4. Audit Log & Compliance Investigations

FreqID records every security-relevant event into an append-only, tamper-evident audit table.

### 4.1 Inspecting Forensic Activity

Navigate to **Audit Log** in the sidebar to review:
- Administrative authentication (logins, failed password attempts, logouts, session timeouts).
- Device operations (pairing token generation, key registration, suspension, revocation).
- Biometric verifications (match decisions, similarity scores, latency, rejected frames).
- User record alterations (enrollment, status toggles, GDPR deletions).

### 4.2 Filtering and Searching

- **Event Type Filter**: Narrow events to `auth`, `device`, `verify`, `enroll`, or `system`.
- **Decision Filter**: Filter by `authenticated`, `rejected`, or `error`.
- **Device Filter**: Isolate events recorded by a specific edge camera.
- **Request ID Tracking**: Every API operation generates an end-to-end correlation ID (e.g., `req-1718000-xyz`). Searching for a Request ID displays the complete request lifecycle across server logs.

### 4.3 Exporting Audit Trails for Regulatory Compliance

Auditors may export forensic logs by clicking **Export CSV**. Specify a date range to download an unalterable CSV log containing timestamps, client IP addresses, actor principals, and cryptographic decisions.

---

## 5. Administrative Accounts & Role Governance

Access to the FreqID Admin Portal is governed by a strict Role-Based Access Control (RBAC) hierarchy.

### 5.1 RBAC Privilege Matrix

| Permission Area | Owner | Admin | Operator | Auditor |
|---|:---:|:---:|:---:|:---:|
| View Dashboard & Telemetry | ✅ | ✅ | ✅ | ✅ |
| View Edge Device Fleet | ✅ | ✅ | ✅ | ✅ |
| Create Device Pairing Tokens | ✅ | ✅ | ❌ | ❌ |
| Suspend / Resume Edge Devices | ✅ | ✅ | ❌ | ❌ |
| Revoke Edge Devices | ✅ | ✅ | ❌ | ❌ |
| View Enrolled Users | ✅ | ✅ | ✅ | ❌ |
| Export User Data (GDPR Art. 15) | ✅ | ✅ | ✅ | ❌ |
| Disable / Enable User Accounts | ✅ | ✅ | ❌ | ❌ |
| Delete User (GDPR Art. 17) | ✅ | ✅ | ❌ | ❌ |
| Inspect Forensic Audit Logs | ✅ | ✅ | ❌ | ✅ |
| Export Audit Trails to CSV | ✅ | ✅ | ❌ | ✅ |
| Create & Manage Admin Accounts | ✅ | ❌ | ❌ | ❌ |
| Update System-Wide Settings | ✅ | ❌ | ❌ | ❌ |

### 5.2 Account Lockout & Brute-Force Defense

To protect administrative accounts against brute-force attacks:
- After **5 consecutive failed login attempts**, the account and calling IP are placed in progressive lockout (starting at 15 minutes).
- The portal interface displays a live countdown timer during lockout.
- All failed authentication attempts generate high-priority security audit events.

---

## 6. Backup, Recovery & Disaster Planning

### 6.1 Database Backups

The core PostgreSQL database contains user identities, encrypted templates, device public keys, and audit logs:
```bash
# Secure dump of PostgreSQL database
pg_dump -U freqid -d freqid -F c -b -v -f /backups/freqid_$(date +%Y%m%d_%H%M%S).dump
```

### 6.2 Key Management

Ensure that server encryption keys (specified in `FREQID_MASTER_KEY` or secret vaults) are backed up securely in offline cold storage. A database dump **cannot be decrypted or restored** without the corresponding master key.

### 6.3 Emergency Device Fleet Lockout

If physical security is breached or an emergency facility lockdown is ordered:
1. Log in as `owner` or `admin`.
2. Navigate to **Devices**.
3. Select affected door turnstiles and click **Suspend Device**.
4. All subsequent badge or face verification requests at those doors will immediately be rejected until manually resumed by an authorized operator.
