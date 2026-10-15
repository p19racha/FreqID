// Copyright 2026 FreqID Authors. Apache-2.0 License.
import { http, HttpResponse } from "msw";

export const mockOwnerUser = {
  id: "adm-00000000-0000-0000-0000-000000000001",
  username: "owner",
  role: "owner" as const,
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

export const mockAdminUser = {
  id: "adm-00000000-0000-0000-0000-000000000002",
  username: "secops",
  role: "admin" as const,
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

export const mockOperatorUser = {
  id: "adm-00000000-0000-0000-0000-000000000003",
  username: "station_op",
  role: "operator" as const,
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

export const mockAuditorUser = {
  id: "adm-00000000-0000-0000-0000-000000000004",
  username: "compliance",
  role: "auditor" as const,
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

export const handlers = [
  // Authentication: Login
  http.post("*/v1/admin/auth/login", async ({ request }) => {
    const body = (await request.json()) as any;
    const { username, password } = body;

    if (username === "locked_user") {
      return HttpResponse.json(
        {
          detail: "Account is temporarily locked due to excessive failed attempts",
          locked_until: new Date(Date.now() + 900000).toISOString(),
        },
        { status: 423 }
      );
    }

    if (username === "owner" && password === "CorrectPassword123!") {
      return HttpResponse.json({
        access_token: "mock-valid-access-token-jwt-secret",
        token_type: "bearer",
        expires_in: 900,
        admin_id: mockOwnerUser.id,
        username: mockOwnerUser.username,
        role: mockOwnerUser.role,
        permissions: ["admin:create", "device:create_pairing_token", "device:list", "device:revoke"],
      });
    }

    if (username === "admin" && password === "CorrectPassword123!") {
      return HttpResponse.json({
        access_token: "mock-admin-access-token",
        token_type: "bearer",
        expires_in: 900,
        admin_id: mockAdminUser.id,
        username: mockAdminUser.username,
        role: mockAdminUser.role,
        permissions: ["device:create_pairing_token", "device:list", "device:revoke"],
      });
    }

    if (username === "operator" && password === "CorrectPassword123!") {
      return HttpResponse.json({
        access_token: "mock-operator-access-token",
        token_type: "bearer",
        expires_in: 900,
        admin_id: mockOperatorUser.id,
        username: mockOperatorUser.username,
        role: mockOperatorUser.role,
        permissions: ["device:list", "user:list", "system:status"],
      });
    }

    if (username === "auditor" && password === "CorrectPassword123!") {
      return HttpResponse.json({
        access_token: "mock-auditor-access-token",
        token_type: "bearer",
        expires_in: 900,
        admin_id: mockAuditorUser.id,
        username: mockAuditorUser.username,
        role: mockAuditorUser.role,
        permissions: ["audit:read", "audit:export_csv", "system:status"],
      });
    }

    // Anti-enumeration failure
    return HttpResponse.json(
      { detail: "Invalid credentials" },
      { status: 401 }
    );
  }),

  // Authentication: Refresh
  http.post("*/v1/admin/auth/refresh", ({ cookies }) => {
    // If invalid cookie or forced refresh fail
    if (cookies.refresh_fail === "1") {
      return HttpResponse.json({ detail: "Invalid refresh token" }, { status: 401 });
    }

    return HttpResponse.json({
      access_token: "mock-refreshed-access-token-jwt",
      token_type: "bearer",
      expires_in: 900,
      admin_id: mockOwnerUser.id,
      username: mockOwnerUser.username,
      role: mockOwnerUser.role,
      permissions: ["admin:create", "device:create_pairing_token", "device:list", "device:revoke"],
    });
  }),

  // Authentication: Logout
  http.post("*/v1/admin/auth/logout", () => {
    return HttpResponse.json({ message: "Successfully logged out" });
  }),

  // Authentication: Current User
  http.get("*/v1/admin/auth/me", ({ request }) => {
    const authHeader = request.headers.get("Authorization");
    if (!authHeader || !authHeader.startsWith("Bearer ")) {
      return HttpResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    return HttpResponse.json(mockOwnerUser);
  }),

  // Devices: List
  http.get("*/v1/admin/devices", () => {
    return HttpResponse.json([
      {
        id: "dev-00000000-0000-0000-0000-000000000001",
        name: "lobby-turnstile-cam-01",
        state: "active",
        scopes: ["verify"],
        key_id: "key-9912",
        software_version: "freqid-client-v0.1.0",
        last_seen: new Date().toISOString(),
        created_at: "2026-02-01T10:00:00Z",
      },
      {
        id: "dev-00000000-0000-0000-0000-000000000002",
        name: "gate-north-cam-02",
        state: "pending",
        scopes: ["identify"],
        key_id: "key-8831",
        software_version: "freqid-client-v0.1.0",
        last_seen: new Date(Date.now() - 60000).toISOString(),
        created_at: "2026-02-02T10:00:00Z",
      },
    ]);
  }),

  // Devices: Create Pairing Token
  http.post("*/v1/admin/devices/pairing-tokens", async ({ request }) => {
    const body = (await request.json()) as any;
    return HttpResponse.json(
      {
        id: "ptok-12345678-abcd-ef01-2345-6789abcdef01",
        token: "pair-128bit-secret-token-random-value",
        expires_at: new Date(Date.now() + (body.expires_in_minutes || 15) * 60000).toISOString(),
        scopes_allowed: ["verify"],
      },
      { status: 201 }
    );
  }),

  // Devices: Revoke
  http.post("*/v1/admin/devices/:deviceId/revoke", async ({ request, params }) => {
    const body = (await request.json()) as any;
    return HttpResponse.json({
      message: `Device ${params.deviceId} revoked`,
      reason: body.reason,
    });
  }),

  // System Status
  http.get("*/v1/admin/system/status", () => {
    return HttpResponse.json({
      model_version: "partialface_ir18_v1",
      gallery_size: 1542,
      queue_depth: 0,
      device_counts: {
        active: 12,
        pending: 1,
        suspended: 0,
        revoked: 3,
      },
      system_load: {
        cpu_pct: 14.2,
        mem_used_bytes: 4294967296,
        mem_total_bytes: 17179869184,
      },
    });
  }),

  // Model Info
  http.get("*/v1/model", () => {
    return HttpResponse.json({
      name: "partialface_ir18_v1",
      checkpoint_sha256: "a4f89d3c52e891b0024f923e4b78c91a78912e65d38a04b12c8e9fa012345678",
      embedding_dim: 512,
      num_frequency_channels: 16,
    });
  }),

  // Audit Query
  http.get("*/v1/admin/audit", () => {
    return HttpResponse.json({
      items: [
        {
          id: "aud-00000000-0000-0000-0000-000000000001",
          event_time: new Date().toISOString(),
          event_type: "biometric_verify",
          principal_type: "device",
          principal_id: "dev-00000000-0000-0000-0000-000000000001",
          user_id: "usr-00000000-0000-0000-0000-000000000001",
          decision: "verified",
          request_id: "req-0192a3b4-1234-789a-bcde-f0123456789a",
          client_ip: "10.0.4.12",
          current_hash: "3b9a1f2e8c4d7b6a5f0e9d8c7b6a5f4e3d2c1b0a9f8e7d6c5b4a3f2e1d0c9b8a",
        },
      ],
      total: 1,
      limit: 20,
    });
  }),
];
