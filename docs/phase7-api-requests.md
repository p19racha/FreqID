# FreqID Phase 7: Backend API Observations & Enhancement Requests

In accordance with **Hard Rule 2** of Phase 7:
> *"Do not modify existing TFace files or any backend or client code. If you need an API change, write it in `freqid/docs/phase7-api-requests.md` (endpoint, reason, suggested shape) and continue with a workaround or stub, then tell me."*

Zero backend or client files were modified during Phase 7. The admin dashboard UI (`freqid-admin-ui`) handles all current backend behaviors robustly using defensive data normalization in client-side queries.

This document records architectural observations, usability enhancements, and schema suggestions identified during the implementation of the 39-endpoint administrative interface.

---

## 1. Pagination Envelope Consistency

### Observation
There is a slight divergence in the response envelope conventions used across collection endpoints in `freqid-server`:
- `GET /v1/admin/audit`: Returns a structured envelope `{ "items": [...], "total": int }`.
- `GET /v1/admin/users`: Returns a raw JSON array `[...]`.
- `GET /v1/admin/devices`: Returns a raw JSON array `[...]`.

### Recommended Shape
Standardize all collection endpoints on a uniform pagination envelope:
```json
{
  "items": [ ... ],
  "total": 1542,
  "limit": 50,
  "offset": 0
}
```

### Front-End Workaround Applied
In `Dashboard.tsx`, `UserList.tsx`, and `DeviceList.tsx`, the client normalizes incoming data defensively:
```typescript
const list = Array.isArray(res.data) ? res.data : (res.data?.items ?? []);
```

---

## 2. Server-Side Device Search Query Parameter

### Endpoint
`GET /v1/admin/devices`

### Current Parameters
- `state` (optional string): Filter by active, pending, suspended, revoked.
- `limit` (optional integer, max 200, default 50).

### Request
Add an optional search parameter:
- `query` (optional string): Case-insensitive substring match against `device.name` and `device.id`.

### Reason
For small deployments (<100 cameras), loading 100 devices and filtering client-side is fast and responsive. For enterprise campus deployments with 500+ access control devices, server-side substring filtering via SQL `ILIKE` will conserve client memory and network bandwidth.

### Front-End Workaround Applied
The UI fetches up to 100 devices and performs responsive in-memory filtering across `name` and `id` in `DeviceList.tsx`.

---

## 3. Comprehensive GDPR Article 15 Archive Bundling

### Endpoint
`GET /v1/admin/users/{user_id}/export`

### Current Response Shape
Returns subject profile metadata, active status, creation date, and template vector summary.

### Suggested Enhancement
Include an embedded array of the user's recent forensic audit events:
```json
{
  "user_id": "usr-123",
  "external_id": "EMP-9921",
  "created_at": "2026-02-15T08:30:00Z",
  "is_active": true,
  "templates_count": 3,
  "model_version": "partialface_ir18_v1",
  "audit_trail": [
    {
      "event_time": "2026-03-01T09:12:00Z",
      "event_type": "verify",
      "decision": "authenticated",
      "device_id": "dev-001"
    }
  ]
}
```

### Reason
Article 15 of the GDPR requires data controllers to provide data subjects with information regarding the processing and access history of their personal data. Having the server automatically bundle the audit history simplifies compliance reporting into a single verifiable cryptographic archive.

### Front-End Workaround Applied
The UI exports the user metadata JSON as delivered by the server and provides a direct link to the filtered audit log for manual inspection.

---

## 4. Bulk Status Update for Edge Devices

### Endpoint
`POST /v1/admin/devices/bulk-action` (New Proposed Endpoint)

### Suggested Shape
```json
{
  "device_ids": ["dev-001", "dev-002", "dev-003"],
  "action": "suspend",
  "reason": "Scheduled facility emergency drill"
}
```

### Reason
During facility emergencies or scheduled site-wide power maintenance, operators currently have to suspend devices individually. A bulk status mutation would allow instant fleet-wide actions with atomic database transactions.

---

## Summary
All endpoints in `freqid/backend/openapi.json` are 100% operational, fully typed in `src/api/v1.d.ts`, and verified with automated drift-detection tests. The recommendations above are non-blocking architectural optimizations for future releases.
