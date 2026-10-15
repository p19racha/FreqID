# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
memory.py: Thread-safe in-memory template store implementation with optional SQLite dev persistence.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import numpy as np

from freqid_server.storage.base import EnrolledTemplate, TemplateStore


class MemoryTemplateStore(TemplateStore):
    """
    In-memory TemplateStore for development, automated testing, and mock validation.
    Optionally synchronizes with a local SQLite database for cross-restart dev persistence.
    """

    def __init__(self, sqlite_path: str = "", persistence_path: str = "") -> None:
        self._templates: dict[str, EnrolledTemplate] = {}
        self._template_versions: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._sqlite_path = (sqlite_path or persistence_path).strip()

        if self._sqlite_path:
            self._init_sqlite()

    def _init_sqlite(self) -> None:
        p = Path(self._sqlite_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._sqlite_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS templates (
                    user_id TEXT PRIMARY KEY,
                    template_id TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    model_version TEXT NOT NULL,
                    enrolled_at_iso TEXT NOT NULL,
                    frames_used INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            cursor = conn.execute(
                "SELECT user_id, template_id, embedding, model_version, enrolled_at_iso, frames_used, metadata_json FROM templates"
            )
            for row in cursor.fetchall():
                u_id, t_id, emb_blob, m_ver, enrolled_at, frames, meta_str = row
                emb = np.frombuffer(emb_blob, dtype=np.float32)
                meta = json.loads(meta_str) if meta_str else {}
                self._templates[u_id] = EnrolledTemplate(
                    user_id=u_id,
                    template_id=t_id,
                    embedding=emb,
                    model_version=m_ver,
                    enrolled_at_iso=enrolled_at,
                    frames_used=frames,
                    metadata=meta,
                )

    async def put_template(self, template: EnrolledTemplate, expected_version: int | None = None) -> None:
        async with self._lock:
            existing = template.user_id in self._templates
            if existing:
                curr_ver = self._template_versions.get(template.user_id, 1)
                if expected_version is not None and curr_ver != expected_version:
                    from freqid_server.errors import OptimisticLockError
                    raise OptimisticLockError(
                        f"Optimistic lock conflict for user '{template.user_id}': expected version {expected_version}, but found {curr_ver}."
                    )
                self._templates[template.user_id] = template
                self._template_versions[template.user_id] = curr_ver + 1
            else:
                self._templates[template.user_id] = template
                self._template_versions[template.user_id] = 1

            if self._sqlite_path:
                with sqlite3.connect(self._sqlite_path) as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO templates 
                        (user_id, template_id, embedding, model_version, enrolled_at_iso, frames_used, metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            template.user_id,
                            template.template_id,
                            template.embedding.tobytes(),
                            template.model_version,
                            template.enrolled_at_iso,
                            template.frames_used,
                            json.dumps(template.metadata),
                        ),
                    )

    async def get_template(self, user_id: str) -> EnrolledTemplate | None:
        async with self._lock:
            return self._templates.get(user_id)

    async def delete_template(self, user_id: str) -> bool:
        async with self._lock:
            existed = user_id in self._templates
            if existed:
                del self._templates[user_id]
                self._template_versions.pop(user_id, None)
                if self._sqlite_path:
                    with sqlite3.connect(self._sqlite_path) as conn:
                        conn.execute("DELETE FROM templates WHERE user_id = ?", (user_id,))
            return existed

    async def delete_user_completely(self, user_id: str) -> bool:
        return await self.delete_template(user_id)

    async def list_templates(self, model_version: str | None = None) -> list[EnrolledTemplate]:
        async with self._lock:
            if model_version is not None:
                return [t for t in self._templates.values() if t.model_version == model_version]
            return list(self._templates.values())

    async def count(self) -> int:
        async with self._lock:
            return len(self._templates)

    async def ping(self) -> bool:
        return True
