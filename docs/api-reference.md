# FreqID API Reference

This document provides a technical specification of the FreqID REST API endpoints, authentication schemes, wire protocols, and error representations.

---

## 1. Authentication Schemes

### 1.1 Edge Device Authentication (Ed25519 Request Signing)
Edge devices authenticate using cryptographic asymmetric request signing:
- Each edge device generates an Ed25519 keypair during the pairing handshake.
- The server stores the public key associated with the device's UUID.
- Every HTTP request must include the following headers:

| Header Name | Type | Description |
| :--- | :--- | :--- |
| `X-Device-ID` | UUID string | Device identifier registered with FreqID. |
| `X-Timestamp` | ISO-8601 string | UTC timestamp of request generation ($\pm 300$s clock window). |
| `X-Nonce` | 32-char hex string | Unique random cryptographic nonce preventing replay attacks. |
| `X-Signature` | Base64 string | Ed25519 digital signature over canonical request string. |

#### Canonical String Construction:
```text
METHOD.PATH.TIMESTAMP.NONCE.SHA256(REQUEST_BODY)
```
Example:
```text
POST./api/v1/auth/verify.2026-10-16T07:00:00Z.a1b2c3d4...<sha256_hex>
```

### 1.2 Administrative Authentication (JWT + HttpOnly Cookie)
Administrators authenticate via `/v1/admin/auth/login`:
- Returns short-lived JSON Web Token (JWT) in response body (`access_token`, TTL: 15 minutes).
- Passes the access token in HTTP header: `Authorization: Bearer <access_token>`.
- Sets a cryptographically random, rotating refresh token in a hardened HTTP cookie:
  `Set-Cookie: freqid_refresh_token=...; HttpOnly; Secure; SameSite=Lax; Path=/v1/admin/auth`.

---

## 2. Health & Observability Endpoints

### 2.1 Liveness Probe
`GET /healthz`
- **Auth**: None (Public)
- **Response**: `200 OK`
  ```json
  {
    "status": "ok",
    "service": "freqid-server"
  }
  ```

### 2.2 Readiness Probe
`GET /readyz`
- **Auth**: None (Public)
- **Response**: `200 OK` (if PostgreSQL and ONNX model runtime are healthy)
  ```json
  {
    "status": "ready",
    "checks": {
      "database": "connected",
      "model": "loaded"
    }
  }
  ```

### 2.3 Prometheus Metrics
`GET /metrics`
- **Auth**: None (Internal Ingress / Monitoring)
- **Response**: `200 OK` (Standard Prometheus Exposition Format)
  ```text
  # HELP freqid_up Heartbeat liveness gauge
  # TYPE freqid_up gauge
  freqid_up 1
  # HELP freqid_store_connected Template store connection status
  # TYPE freqid_store_connected gauge
  freqid_store_connected 1
  # HELP freqid_model_loaded Biometric inference engine status
  # TYPE freqid_model_loaded gauge
  freqid_model_loaded 1
  # HELP freqid_enrolled_identities Total count of enrolled biometric identities
  # TYPE freqid_enrolled_identities gauge
  freqid_enrolled_identities 142
  ```

---

## 3. Biometric Operations

### 3.1 1:1 Biometric Verification
`POST /api/v1/auth/verify` or `POST /v1/verify`
- **Auth**: Device (`verify` scope)
- **Content-Type**: `application/vnd.freqid.payload`
- **Headers**:
  - `X-Claimed-Identity`: User identifier being verified (e.g., `alice_smith`).
- **Body**: Serialized 27-channel `PartialFacePayload` bytes.
- **Response**: `200 OK`
  ```json
  {
    "status": "success",
    "request_id": "aa4b7652-42df-4894-8119-cc1854e2654e",
    "is_match": true,
    "similarity": null,
    "threshold": 0.35,
    "claimed_identity": "alice_smith",
    "verified_identity": "alice_smith",
    "device_id": "bf05e20f-79cd-4a81-8d9c-69d2a4e54baa"
  }
  ```
  *Note on Score Masking*: In production (`FREQID_SERVER_MASK_SCORES_IN_PRODUCTION=true`), `similarity` is returned as `null` to prevent hill-climbing facial reconstruction attacks.
  *Anti-Enumeration*: If `claimed_identity` does not exist, the API returns `200 OK` with `is_match: false` and `verified_identity: null`.

### 3.2 1:N Biometric Identification
`POST /api/v1/auth/identify` or `POST /v1/identify`
- **Auth**: Device (`identify` scope)
- **Content-Type**: `application/vnd.freqid.payload`
- **Body**: Serialized 27-channel `PartialFacePayload` bytes.
- **Response**: `200 OK`
  ```json
  {
    "status": "success",
    "request_id": "4e75c120-...",
    "is_match": true,
    "top_candidate": {
      "user_id": "alice_smith",
      "similarity": null
    },
    "candidates_count": 1
  }
  ```

### 3.3 Multi-Frame Biometric Enrollment
`POST /api/v1/enroll/frames` or `POST /v1/enroll`
- **Auth**: Device (`enroll` scope)
- **Headers**:
  - `X-User-ID`: Unique user identifier to enroll.
  - `X-Payload-Count`: Integer count of frames packed in body ($N \ge 1$).
  - `X-Re-Enroll`: (Optional) `true` to replace existing enrollment.
- **Body**: Contiguous concatenation of $N$ serialized `PartialFacePayload` frames.
- **Response**: `201 Created`
  ```json
  {
    "status": "enrolled",
    "user_id": "alice_smith",
    "template_id": "tmpl_alice_smith_1792134178237",
    "frames_processed": 3,
    "frames_accepted": 3,
    "outliers_rejected": 0,
    "quality_score": 0.96,
    "duplicate_warning": null
  }
  ```

### 3.4 Identity Template Deletion
`DELETE /api/v1/users/{user_id}` or `DELETE /v1/users/{user_id}`
- **Auth**: Admin or Device (`enroll` scope)
- **Response**: `200 OK`
  ```json
  {
    "status": "deleted",
    "message": "Biometric template for user 'alice_smith' has been permanently deleted."
  }
  ```

---

## 4. Device Lifecycle Operations

### 4.1 Device Pairing Handshake
`POST /api/v1/devices/pair`
- **Auth**: One-time pairing token in body
- **Body**:
  ```json
  {
    "token": "PAIR_a1b2c3d4...",
    "public_key": "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A...",
    "device_name": "kiosk-front-gate",
    "software_version": "0.1.0"
  }
  ```
- **Response**: `201 Created`
  ```json
  {
    "status": "paired",
    "device_id": "bf05e20f-79cd-4a81-8d9c-69d2a4e54baa",
    "assigned_scopes": ["verify", "enroll"]
  }
  ```

### 4.2 Device Heartbeat & Telemetry
`POST /api/v1/devices/heartbeat`
- **Auth**: Device signature
- **Body**:
  ```json
  {
    "status": "online",
    "metrics": {
      "uptime_seconds": 86400,
      "cpu_load": 0.15,
      "memory_mb": 512
    }
  }
  ```
- **Response**: `200 OK`

---

## 5. Administrative Operations

### 5.1 Admin Authentication
- `POST /v1/admin/auth/login`: Accepts `{"username": "...", "password": "..."}`. Returns JWT and sets HttpOnly refresh cookie.
- `POST /v1/admin/auth/refresh`: Exchanges refresh cookie for new access token.
- `POST /v1/admin/auth/logout`: Revokes refresh token and clears cookie.

### 5.2 Device Management
- `GET /v1/admin/devices`: List all registered devices, status (`active`, `suspended`, `revoked`), and last heartbeat.
- `POST /v1/admin/devices/pairing-tokens`: Create one-time pairing token (`{"name_hint": "...", "scopes": [...]}`).
- `POST /v1/admin/devices/{id}/suspend`: Temporarily suspend device (requests return 403).
- `POST /v1/admin/devices/{id}/resume`: Resume suspended device.
- `POST /v1/admin/devices/{id}/revoke`: Permanently revoke device credentials.
- `DELETE /v1/admin/devices/{id}`: Delete revoked device metadata.

### 5.3 Audit Log & Export
- `GET /v1/admin/audit`: Query tamper-evident audit log with filtering on `event_type`, `principal_type`, `date_range`, and pagination.
- `GET /v1/admin/audit/export`: Export filtered audit records to CSV format.

---

## 6. Standard Error Response Envelope

All API errors return a uniform JSON error envelope:
```json
{
  "error": {
    "code": "DUPLICATE_IDENTITY",
    "message": "User 'alice_smith' is already enrolled. Pass re_enroll=true or X-Re-Enroll: true header to replace.",
    "request_id": "5cdf8ca9-313e-4c80-9537-71ebefc55a50"
  },
  "detail": {
    "error_code": "DUPLICATE_IDENTITY",
    "message": "User 'alice_smith' is already enrolled."
  }
}
```

### Common Error Codes:
| HTTP Status | Error Code | Description |
| :--- | :--- | :--- |
| `400` | `INVALID_PAYLOAD` | Transmitted payload bytes do not conform to PartialFace binary format. |
| `401` | `UNAUTHORIZED` | Invalid credentials, expired token, or signature verification failure. |
| `403` | `INSUFFICIENT_SCOPE` | Authenticated principal lacks required permission scope. |
| `403` | `DEVICE_SUSPENDED` | Edge device has been suspended by an administrator. |
| `403` | `DEVICE_REVOKED` | Edge device credentials have been permanently revoked. |
| `404` | `NOT_FOUND` | Requested administrative resource does not exist. |
| `409` | `DUPLICATE_IDENTITY` | Identity already enrolled; explicit re-enroll flag required. |
| `429` | `RATE_LIMIT_EXCEEDED` | Request rate exceeds configured client threshold (HTTP headers indicate reset window). |
