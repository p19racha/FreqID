# FreqID Key Management Guide & Operational Runbook

This document defines the lifecycle, derivation hierarchy, backup protocols, zero-downtime rotation procedures, and disaster recovery runbooks for all cryptographic keys across the FreqID ecosystem.

---

## 1. Key Architecture & Roles

FreqID employs a multi-tiered cryptographic hierarchy anchored in an active **Master Key (Root of Trust)**. Rather than using the master key directly for data encryption, FreqID derives purpose-specific subkeys via **HKDF-SHA256** ([RFC 5869](https://tools.ietf.org/html/rfc5869)).

```
                                +-------------------+
                                |    Master Key     |
                                | 256-bit Root Seed |
                                +---------+---------+
                                          |
                        +-----------------+-----------------+
                        |   HKDF-SHA-256 (Purpose Context)  |
                        +-----------------+-----------------+
                                          |
      +-----------------+-----------------+-----------------+-----------------+
      |                 |                 |                 |                 |
+-----v-----+     +-----v-----+     +-----v-----+     +-----v-----+     +-----v-----+
| template  |     | transform |     |   audit   |     |   token   |     |  payload  |
| 256-bit   |     | 256-bit   |     | 256-bit   |     | 256-bit   |     | X25519    |
| KEK       |     | Seed R    |     | HMAC Key  |     | HMAC Key  |     | Keypair   |
+-----+-----+     +-----+-----+     +-----------+     +-----------+     +-----------+
      |                 |
      |                 v
      |         Haar Orthogonal
      |         Matrix R in O(512)
      v
+-----------+
| Wrap DEK  |
| (Per-Tmpl)|
+-----------+
```

### Purpose Key Inventory

| Purpose ID | Algorithm | Context String | Operational Usage |
| :--- | :--- | :--- | :--- |
| **`template`** | AES-256-GCM | `freqid-template-kek-v1` | **Key Encryption Key (KEK)**: Wraps ephemeral per-template 256-bit Data Encryption Keys (DEKs). |
| **`transform`** | SHA-512 / PRNG | `freqid-cancelable-transform-v1` | **Cancelable Biometric Seed**: Generates the deterministic Haar orthogonal matrix $R \in \mathbb{O}(512)$ for template projection. |
| **`audit`** | HMAC-SHA256 | `freqid-audit-log-hmac-v1` | **Log Integrity**: Computes cryptographic HMAC chains across immutable audit event rows. |
| **`token`** | HMAC-SHA256 | `freqid-token-signing-v1` | **Token Verification**: Derives validation keys for device pairing tokens and internal tokens. |
| **`payload`** | X25519 (Ed25519 curve) | `freqid-payload-sealing-x25519-v1` | **Payload Sealing**: Server private/public keypair used in application-layer envelope sealing (`PF02`). |

---

## 2. Master Key Lifecycle

### 2.1 Generation

The master key is a 256-bit (32-byte) cryptographically secure random value obtained from the OS entropy source (`os.urandom(32)` via `getrandom(2)`).

To generate a new master key:
```bash
# Using the CLI utility
python scripts/freqid_keys.py generate -o /etc/freqid/keys/master_key_2026_v1.key

# Verify file permissions (enforces 0600)
ls -la /etc/freqid/keys/master_key_2026_v1.key
# -rw------- 1 freqid freqid 45 Oct 15 10:00 /etc/freqid/keys/master_key_2026_v1.key
```

### 2.2 Storage & Loading

The backend [`EnvOrFileKeyProvider`](file:///home/racha/FreqID/backend/src/freqid_server/crypto/provider.py) resolves keys in the following order of precedence:

1. **Direct Parameter**: Initialized via in-memory byte buffer (test harnesses, HSM wrappers).
2. **Key File (`master_key_file`)**: Path configured in YAML config or `FREQID_MASTER_KEY_FILE` environment variable.
3. **Environment Variable (`FREQID_MASTER_KEY`)**: Base64-encoded or Hex-encoded 32-byte key string.

> [!IMPORTANT]
> Key files must be owned by the service user (e.g. `freqid:freqid`) with file mode `0600` (`-rw-------`). Any world- or group-readable permissions should trigger deployment pipeline failure.

### 2.3 Verification & Subkey Inspection

To verify the integrity and fingerprints of derived subkeys without exposing secret material:
```bash
python scripts/freqid_keys.py subkeys --key-file /etc/freqid/keys/master_key_2026_v1.key
```
Output:
```text
Master Key Hierarchy Status:
  Active Key ID: active_key
  Subkey 'template ': SHA-256 fingerprint: a3f8902c4b12df89 (32 bytes)
  Subkey 'transform': SHA-256 fingerprint: 71cb9431e28901ba (32 bytes)
  Subkey 'audit    ': SHA-256 fingerprint: 4920cd99ef1a8301 (32 bytes)
  Subkey 'token    ': SHA-256 fingerprint: c18a09f87239d10e (32 bytes)
  Subkey 'payload  ': X25519 public key (hex): 8f31b2c4e97a1d...
```

---

## 3. Shamir Secret Sharing Backup Runbook (SLIP-0039)

To prevent total data loss in catastrophic disaster scenarios without creating a single high-value digital backup target, FreqID implements **SLIP-0039 Shamir's Secret Sharing for Mnemonic Codes**.

### 3.1 Splitting Ceremony

A typical production configuration utilizes a **$3$-of-$5$ threshold scheme**: any 3 of 5 authorized custodians can reconstruct the master key, while any 2 colluding parties gain zero information.

```bash
# Execute the splitting ceremony on an air-gapped machine
python scripts/freqid_keys.py split \
    --key-file /etc/freqid/keys/master_key_2026_v1.key \
    -k 3 \
    -n 5
```

Sample output:
```text
================================================================================
 FreqID Shamir Secret Sharing Backup (SLIP-0039 Standard)
 Master Key Fingerprint (SHA-256[:8]): 8c7210dfa92b01ef
 Scheme: 3-of-5 threshold recovery
================================================================================
Each share below contains error detection and group parameters.
Distribute these shares to separate custodians or distinct physical locations.
Any 3 shares can fully reconstruct the master key.
--------------------------------------------------------------------------------

--- [SHARE 1/5] ---
crater award acid acne academic adapt animal axle beaver blanket blue cargo
ceramic champion clarify claw clue comedy cousin crater cradle crawl credit crisis

--- [SHARE 2/5] ---
crater award acid acne acrobat adjust album armed biology blend branch buyer
cement clarify client clone code cosmic criminal crucial crush cube curtain dance

--- [SHARE 3/5] ---
crater award acid acne alcohol agency alpha biology blush breeze brisk buyer
center clarify cliff club column costume debate declare delay deputy dive draft

--- [SHARE 4/5] ---
crater award acid acne actress alien anchor biology board broken bubble buyer
change clarify clinic clump comic counter decline degree delta desert doctor dry

--- [SHARE 5/5] ---
crater award acid acne adult alive ancient biology bother bronze bucket buyer
charge clarify clock coach convert country decrease delay device divorce drama dusk
--------------------------------------------------------------------------------
```

#### Custodian Protocol Rules
1. **Physical Segregation**: Shares 1 through 5 must be printed on tamper-evident archival paper and placed in sealed envelopes within distinct physical fireproof safes or bank deposit boxes.
2. **Fingerprint Recording**: All custodians must independently verify and record the 8-character fingerprint (`8c7210dfa92b01ef`).
3. **No Digital Storage**: Shares must **never** be copied into digital password managers, chat channels, emails, or version control.

### 3.2 Reconstruction Ceremony

When restoring from a catastrophic outage or server migration:
```bash
python scripts/freqid_keys.py combine -o /etc/freqid/keys/recovered_master.key
```
Interactive prompt:
```text
Enter Shamir mnemonic shares one per line (end with an empty line or EOF):
> crater award acid acne academic adapt animal axle beaver blanket blue cargo ceramic champion clarify claw clue comedy cousin crater cradle crawl credit crisis
> crater award acid acne acrobat adjust album armed biology blend branch buyer cement clarify client clone code cosmic criminal crucial crush cube curtain dance
> crater award acid acne alcohol agency alpha biology blush breeze brisk buyer center clarify cliff club column costume debate declare delay deputy dive draft
> 

[*] Successfully reconstructed master key!
    Fingerprint (SHA-256[:8]): 8c7210dfa92b01ef
    Base64: [REDACTED]
[*] Reconstructed key written to: /etc/freqid/keys/recovered_master.key (permissions 0600)
```

The script automatically validates the SLIP-0039 Reed-Solomon checksums; corrupted or mismatched shares are rejected immediately.

---

## 4. Key Rotation Procedures

FreqID supports **zero-downtime key rotation** using key ring versioning. Biometric templates stored in PostgreSQL record their wrapping `key_id` and `format_version` alongside ciphertext.

### 4.1 Master Key Rotation (KEK Re-wrapping)

When rotating the master key:
1. Generate new master key `master_key_2027_v2.key` with key ID `2027_v2`.
2. Add the previous key ID `2026_v1` to the server's key ring dictionary in [`provider.py`](file:///home/racha/FreqID/backend/src/freqid_server/crypto/provider.py):
   ```python
   key_ring = {
       "2026_v1": previous_key_bytes,
       "2027_v2": new_active_key_bytes,
   }
   ```
3. Set `active_key_id: "2027_v2"`.
4. Deploy the configuration. The server continues reading templates encrypted under `2026_v1` while encrypting new enrollments under `2027_v2`.
5. Background migration: Re-wrap existing Data Encryption Keys (DEKs) by decrypting `wrapped_data_key` with the old KEK and re-encrypting it with the new KEK. Raw embeddings do not need to be loaded into memory.

### 4.2 Format Version & Orthogonal Matrix Migration (v1 to v2)

To migrate templates from format version 1 (unrotated plain embeddings) to format version 2 (cancelable orthogonal transformation $R \in \mathbb{O}(512)$):

#### Step 1: Pre-flight Dry Run
```bash
python scripts/migrate_templates.py --dry-run
```
Output:
```text
[*] FreqID Template Migration to Format Version 2
    Database URL: localhost:5432/freqid
    Mode: DRY RUN (no DB modifications)
[*] Current template population: total=1500
    Format v1 (Legacy unrotated): 1500
    Format v2 (Rotated O(512)) : 0
[*] Dry-run complete. 1500 templates would be migrated in ~15 batches.
```

#### Step 2: Live Batched Migration
Execute migration during regular operation. Online verification and identification traffic continues uninterrupted:
```bash
python scripts/migrate_templates.py --batch-size 100 --target-format 2
```
Output:
```text
[*] FreqID Template Migration to Format Version 2
    Database URL: localhost:5432/freqid
    Mode: LIVE MIGRATION
    Migrated batch: 100/1500 templates...
    Migrated batch: 200/1500 templates...
    ...
    Migrated batch: 1500/1500 templates...
[+] Successfully migrated 1500 templates in 4.12s (364.1 tmpl/s).
```

### 4.3 Payload Public Key Rotation

Edge devices encrypt payload envelopes using the server's ephemeral X25519 public key obtained via `GET /v1/payload-key`.
- When the server rotates its master key or `payload` subkey, the public key fingerprint automatically updates.
- Clients automatically refresh their cached server public key upon encountering an authentication error or expiration interval (default 24h).

---

## 5. Compromise Recovery & Incident Response

### Severity Matrix & Action Protocols

```
+-------------------------------------------------------------------------------+
| INCIDENT SCENARIO          | IMPACT RADIUS     | IMMEDIATE ACTION             |
+----------------------------+-------------------+------------------------------+
| A. Edge Device Stolen/Lost | Single device ID  | Instant Revocation in UI     |
| B. Device Private Key Leak | Single device CN  | CA CRL / Server Denylist     |
| C. DB Dump Leaked (Only)   | Encrypted Blobs   | None (Blobs uninvertible)    |
| D. Server Master Key Leak  | Entire deployment | Full Key Rotation & Re-wrap  |
+-------------------------------------------------------------------------------+
```

### Scenario A: Edge Device Physical Compromise or Theft
1. **Immediate Revocation**: An administrator navigates to **Admin UI -> Devices** and clicks **Revoke Device**, or issues:
   ```bash
   curl -X POST https://freqid.internal/v1/admin/devices/{device_id}/revoke \
     -H "Authorization: Bearer $ADMIN_JWT" \
     -H "Content-Type: application/json" \
     -d '{"reason": "Physical theft reported"}'
   ```
2. **Verification**: Confirm in the audit log that the device's requests immediately receive `401 Unauthorized` / `403 Forbidden`. The in-memory cache drops the device state within milliseconds.

### Scenario B: Device Transport Key or Certificate Leak
1. Re-issue client credentials:
   ```bash
   # Revoke old cert and issue fresh certificate
   python scripts/generate_device_cert.py issue-device \
       --device-id edge-station-04 \
       --ca-cert deploy/tls/certs/ca.crt \
       --ca-key deploy/tls/certs/ca.key
   ```
2. Update the device configuration with the new certificate and private key.

### Scenario C: Database Exfiltration (Without Master Key)
- Biometric records are stored in format v2: encrypted with AES-256-GCM using wrapped DEKs, and the underlying vectors are transformed by $R \in \mathbb{O}(512)$.
- Empirical evaluation (Attack 7) confirms:
  - 100% of biometric templates are encrypted at rest.
  - Zero raw or rotated embeddings can be parsed without the master key.
  - Offline match rate without the key is $0.0\%$.
- **Action**: Identify and patch the SQL injection or database unauthorized access vulnerability. No immediate template re-enrollment is required.

### Scenario D: Master Key Exfiltration
If the master key itself is suspected or confirmed leaked:
1. **Declare Incident**: Immediately sever public ingress to the FreqID server.
2. **Issue New Master Key**: Run `python scripts/freqid_keys.py generate -o /etc/freqid/keys/master_key_new.key`.
3. **Derive New Orthogonal Matrix**: A new `transform` subkey yields matrix $R_{new}$.
4. **Re-transform Templates**: Run the migration utility with the old key and new key configured to decrypt from $R_{old}$ and re-encrypt under $R_{new}$. Because $R_{new}$ is orthogonal and independent, any copy of the templates exfiltrated with the old key cannot be matched against the new database (unlinkability cross-correlation $\rho \approx 0.0$).
5. **Re-pair Devices**: Revoke existing pairing tokens and issue fresh pairing credentials for all registered edge devices.
