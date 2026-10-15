# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
permissions.py: Role-based permission matrix and FastAPI dependency enforcement.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final, Literal

from fastapi import Depends

from freqid_server.auth.base import AuthenticatedPrincipal
from freqid_server.errors import AuthenticationError, InsufficientScopeError

AdminRole = Literal["owner", "admin", "operator", "auditor"]

# Standardized permission strings
PERM_ADMIN_CREATE: Final = "admin:create"
PERM_ADMIN_LIST: Final = "admin:list"
PERM_ADMIN_READ: Final = "admin:read"
PERM_ADMIN_UPDATE_ROLE: Final = "admin:update_role"
PERM_ADMIN_DISABLE: Final = "admin:disable"
PERM_ADMIN_UNLOCK: Final = "admin:unlock"

PERM_SETTINGS_READ: Final = "settings:read"
PERM_SETTINGS_UPDATE: Final = "settings:update"

PERM_DEVICE_CREATE_PAIRING: Final = "device:create_pairing_token"
PERM_DEVICE_LIST: Final = "device:list"
PERM_DEVICE_READ: Final = "device:read"
PERM_DEVICE_APPROVE: Final = "device:approve"
PERM_DEVICE_SUSPEND: Final = "device:suspend"
PERM_DEVICE_RESUME: Final = "device:resume"
PERM_DEVICE_REVOKE: Final = "device:revoke"
PERM_DEVICE_DELETE_REVOKED: Final = "device:delete_revoked"
PERM_DEVICE_UPDATE_SCOPES: Final = "device:update_scopes"

PERM_USER_LIST: Final = "user:list"
PERM_USER_READ: Final = "user:read"
PERM_USER_ENROLL: Final = "user:enroll"
PERM_USER_DISABLE: Final = "user:disable"
PERM_USER_ENABLE: Final = "user:enable"
PERM_USER_DELETE: Final = "user:delete"
PERM_USER_EXPORT: Final = "user:export"

PERM_AUDIT_READ: Final = "audit:read"
PERM_AUDIT_EXPORT_CSV: Final = "audit:export_csv"

PERM_SYSTEM_STATUS: Final = "system:status"

# Master permission matrix by role
ROLE_PERMISSIONS: Final[dict[str, frozenset[str]]] = {
    "owner": frozenset(
        {
            PERM_ADMIN_CREATE,
            PERM_ADMIN_LIST,
            PERM_ADMIN_READ,
            PERM_ADMIN_UPDATE_ROLE,
            PERM_ADMIN_DISABLE,
            PERM_ADMIN_UNLOCK,
            PERM_SETTINGS_READ,
            PERM_SETTINGS_UPDATE,
            PERM_DEVICE_CREATE_PAIRING,
            PERM_DEVICE_LIST,
            PERM_DEVICE_READ,
            PERM_DEVICE_APPROVE,
            PERM_DEVICE_SUSPEND,
            PERM_DEVICE_RESUME,
            PERM_DEVICE_REVOKE,
            PERM_DEVICE_DELETE_REVOKED,
            PERM_DEVICE_UPDATE_SCOPES,
            PERM_USER_LIST,
            PERM_USER_READ,
            PERM_USER_ENROLL,
            PERM_USER_DISABLE,
            PERM_USER_ENABLE,
            PERM_USER_DELETE,
            PERM_USER_EXPORT,
            PERM_AUDIT_READ,
            PERM_AUDIT_EXPORT_CSV,
            PERM_SYSTEM_STATUS,
        }
    ),
    "admin": frozenset(
        {
            PERM_ADMIN_LIST,
            PERM_ADMIN_READ,
            PERM_SETTINGS_READ,
            PERM_DEVICE_CREATE_PAIRING,
            PERM_DEVICE_LIST,
            PERM_DEVICE_READ,
            PERM_DEVICE_APPROVE,
            PERM_DEVICE_SUSPEND,
            PERM_DEVICE_RESUME,
            PERM_DEVICE_REVOKE,
            PERM_DEVICE_UPDATE_SCOPES,
            PERM_USER_LIST,
            PERM_USER_READ,
            PERM_USER_ENROLL,
            PERM_USER_DISABLE,
            PERM_USER_ENABLE,
            PERM_USER_DELETE,
            PERM_USER_EXPORT,
            PERM_AUDIT_READ,
            PERM_AUDIT_EXPORT_CSV,
            PERM_SYSTEM_STATUS,
        }
    ),
    "operator": frozenset(
        {
            PERM_SETTINGS_READ,
            PERM_DEVICE_LIST,
            PERM_DEVICE_READ,
            PERM_USER_LIST,
            PERM_USER_READ,
            PERM_USER_ENROLL,
            PERM_SYSTEM_STATUS,
        }
    ),
    "auditor": frozenset(
        {
            PERM_SETTINGS_READ,
            PERM_DEVICE_LIST,
            PERM_DEVICE_READ,
            PERM_AUDIT_READ,
            PERM_AUDIT_EXPORT_CSV,
            PERM_SYSTEM_STATUS,
        }
    ),
}


def get_permissions_for_role(role: str) -> frozenset[str]:
    """Returns the set of permissions granted to a given role."""
    return ROLE_PERMISSIONS.get(role, frozenset())


def role_has_permission(role: str, permission: str) -> bool:
    """Checks whether a role possesses a specific permission."""
    return permission in get_permissions_for_role(role)
