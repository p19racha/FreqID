# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
base.py: Abstract storage interface for biometric identity templates.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class EnrolledTemplate:
    """Represents a persisted biometric face template."""

    user_id: str
    template_id: str
    embedding: np.ndarray  # 512-D float32 L2-normalized vector
    model_version: str  # e.g., "v1.0-ir18"
    enrolled_at_iso: str  # ISO-8601 string
    frames_used: int  # Number of partial frequency captures averaged
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.embedding.shape != (512,):
            raise ValueError(
                f"Template embedding must have shape (512,), got {self.embedding.shape}"
            )
        if self.embedding.dtype != np.float32:
            object.__setattr__(self, "embedding", self.embedding.astype(np.float32))


class TemplateStore(ABC):
    """
    Abstract contract for template persistence.
    Phase 4 provides MemoryTemplateStore (in-memory + dev SQLite).
    Phase 5 provides PostgreSQLTemplateStore with pgvector.
    """

    @abstractmethod
    async def put_template(
        self, template: EnrolledTemplate, expected_version: int | None = None
    ) -> None:
        """Stores or replaces a template record for template.user_id, with optional optimistic lock version."""

    @abstractmethod
    async def get_template(self, user_id: str) -> EnrolledTemplate | None:
        """Retrieves template by user_id. Returns None if not found."""

    @abstractmethod
    async def delete_template(self, user_id: str) -> bool:
        """Permanently removes user template. Returns True if existed, False otherwise."""

    @abstractmethod
    async def delete_user_completely(self, user_id: str) -> bool:
        """
        Right-to-be-forgotten: removes user profile, template, sessions,
        and anonymizes historical audit rows.
        """

    @abstractmethod
    async def list_templates(self, model_version: str | None = None) -> list[EnrolledTemplate]:
        """Loads all active templates (used to initialize in-memory gallery index)."""

    @abstractmethod
    async def count(self) -> int:
        """Returns total number of enrolled identities."""

    @abstractmethod
    async def ping(self) -> bool:
        """Health probe returning True if storage backend is accessible."""
