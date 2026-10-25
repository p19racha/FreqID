# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
base.py: Abstract authentication interface and security principal definition.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from fastapi import Request


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Security principal extracted from authenticated request."""

    principal_id: str  # Device ID or Admin ID
    principal_type: str  # "device" or "admin"
    scopes: set[str] = field(default_factory=set)

    def has_scope(self, scope: str) -> bool:
        """Returns True if principal holds the required permission scope."""
        return scope in self.scopes or "admin" in self.scopes


class RequestAuthenticator(ABC):
    """Abstract interface for request authentication."""

    @abstractmethod
    async def authenticate(
        self, request: Request, required_scope: str | None = None
    ) -> AuthenticatedPrincipal:
        """
        Authenticates incoming HTTP request.
        Raises AuthenticationError or InsufficientScopeError on failure.
        """
