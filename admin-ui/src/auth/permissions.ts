// Copyright 2026 FreqID Authors. Apache-2.0 License.
/**
 * permissions.ts: Front-end role-based access control matrix.
 * Strictly synchronized with backend/src/freqid_server/auth/permissions.py.
 * Verified against drift in CI via permissions-drift.test.ts.
 */

export const PERMISSIONS = {
  // Admin management (Owner only)
  ADMIN_CREATE: "admin:create",
  ADMIN_LIST: "admin:list",
  ADMIN_READ: "admin:read",
  ADMIN_UPDATE_ROLE: "admin:update_role",
  ADMIN_DISABLE: "admin:disable",
  ADMIN_UNLOCK: "admin:unlock",

  // System settings
  SETTINGS_READ: "settings:read",
  SETTINGS_UPDATE: "settings:update",

  // Device management
  DEVICE_CREATE_PAIRING: "device:create_pairing_token",
  DEVICE_LIST: "device:list",
  DEVICE_READ: "device:read",
  DEVICE_APPROVE: "device:approve",
  DEVICE_SUSPEND: "device:suspend",
  DEVICE_RESUME: "device:resume",
  DEVICE_REVOKE: "device:revoke",
  DEVICE_DELETE_REVOKED: "device:delete_revoked",
  DEVICE_UPDATE_SCOPES: "device:update_scopes",

  // User identities & templates
  USER_LIST: "user:list",
  USER_READ: "user:read",
  USER_ENROLL: "user:enroll",
  USER_DISABLE: "user:disable",
  USER_ENABLE: "user:enable",
  USER_DELETE: "user:delete",
  USER_EXPORT: "user:export",

  // Audit logs
  AUDIT_READ: "audit:read",
  AUDIT_EXPORT_CSV: "audit:export_csv",

  // System status
  SYSTEM_STATUS: "system:status",
} as const;

export type Permission = (typeof PERMISSIONS)[keyof typeof PERMISSIONS];
export type AdminRole = "owner" | "admin" | "operator" | "auditor";

export const ROLE_PERMISSIONS: Record<AdminRole, ReadonlySet<string>> = {
  owner: new Set([
    PERMISSIONS.ADMIN_CREATE,
    PERMISSIONS.ADMIN_LIST,
    PERMISSIONS.ADMIN_READ,
    PERMISSIONS.ADMIN_UPDATE_ROLE,
    PERMISSIONS.ADMIN_DISABLE,
    PERMISSIONS.ADMIN_UNLOCK,
    PERMISSIONS.SETTINGS_READ,
    PERMISSIONS.SETTINGS_UPDATE,
    PERMISSIONS.DEVICE_CREATE_PAIRING,
    PERMISSIONS.DEVICE_LIST,
    PERMISSIONS.DEVICE_READ,
    PERMISSIONS.DEVICE_APPROVE,
    PERMISSIONS.DEVICE_SUSPEND,
    PERMISSIONS.DEVICE_RESUME,
    PERMISSIONS.DEVICE_REVOKE,
    PERMISSIONS.DEVICE_DELETE_REVOKED,
    PERMISSIONS.DEVICE_UPDATE_SCOPES,
    PERMISSIONS.USER_LIST,
    PERMISSIONS.USER_READ,
    PERMISSIONS.USER_ENROLL,
    PERMISSIONS.USER_DISABLE,
    PERMISSIONS.USER_ENABLE,
    PERMISSIONS.USER_DELETE,
    PERMISSIONS.USER_EXPORT,
    PERMISSIONS.AUDIT_READ,
    PERMISSIONS.AUDIT_EXPORT_CSV,
    PERMISSIONS.SYSTEM_STATUS,
  ]),

  admin: new Set([
    PERMISSIONS.ADMIN_LIST,
    PERMISSIONS.ADMIN_READ,
    PERMISSIONS.SETTINGS_READ,
    PERMISSIONS.DEVICE_CREATE_PAIRING,
    PERMISSIONS.DEVICE_LIST,
    PERMISSIONS.DEVICE_READ,
    PERMISSIONS.DEVICE_APPROVE,
    PERMISSIONS.DEVICE_SUSPEND,
    PERMISSIONS.DEVICE_RESUME,
    PERMISSIONS.DEVICE_REVOKE,
    PERMISSIONS.DEVICE_UPDATE_SCOPES,
    PERMISSIONS.USER_LIST,
    PERMISSIONS.USER_READ,
    PERMISSIONS.USER_ENROLL,
    PERMISSIONS.USER_DISABLE,
    PERMISSIONS.USER_ENABLE,
    PERMISSIONS.USER_DELETE,
    PERMISSIONS.USER_EXPORT,
    PERMISSIONS.AUDIT_READ,
    PERMISSIONS.AUDIT_EXPORT_CSV,
    PERMISSIONS.SYSTEM_STATUS,
  ]),

  operator: new Set([
    PERMISSIONS.SETTINGS_READ,
    PERMISSIONS.DEVICE_LIST,
    PERMISSIONS.DEVICE_READ,
    PERMISSIONS.USER_LIST,
    PERMISSIONS.USER_READ,
    PERMISSIONS.USER_ENROLL,
    PERMISSIONS.SYSTEM_STATUS,
  ]),

  auditor: new Set([
    PERMISSIONS.SETTINGS_READ,
    PERMISSIONS.DEVICE_LIST,
    PERMISSIONS.DEVICE_READ,
    PERMISSIONS.AUDIT_READ,
    PERMISSIONS.AUDIT_EXPORT_CSV,
    PERMISSIONS.SYSTEM_STATUS,
  ]),
};

export function hasPermission(role: string | undefined | null, permission: Permission): boolean {
  if (!role) return false;
  const roleSet = ROLE_PERMISSIONS[role as AdminRole];
  if (!roleSet) return false;
  return roleSet.has(permission);
}
