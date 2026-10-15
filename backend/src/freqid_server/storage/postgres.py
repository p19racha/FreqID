# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
postgres.py: Production PostgreSQL implementation of TemplateStore with envelope encryption.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from freqid_server.crypto.envelope import EncryptedTemplateRecord, TemplateEncryptor
from freqid_server.errors import OptimisticLockError
from freqid_server.storage.base import EnrolledTemplate, TemplateStore
from freqid_server.storage.models import TemplateOrm, UserOrm


class PostgreSQLTemplateStore(TemplateStore):
    """
    PostgreSQL-backed biometric template store.
    Enforces record-bound AES-256-GCM encryption at rest, optimistic locking,
    keyset streaming pagination, and complete GDPR/CCPA anonymized deletion.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        encryptor: TemplateEncryptor,
        batch_size: int = 1000,
    ) -> None:
        self.session_factory = session_factory
        self.encryptor = encryptor
        self.batch_size = batch_size

    async def put_template(
        self,
        template: EnrolledTemplate,
        expected_version: int | None = None,
    ) -> None:
        """
        Stores or updates an encrypted biometric template in an atomic transaction.
        Checks optimistic lock version if expected_version is provided.
        """
        async with self.session_factory() as session, session.begin():
            # 1. Fetch or create User profile
            stmt_user = select(UserOrm).where(UserOrm.external_id == template.user_id)
            res_user = await session.execute(stmt_user)
            user = res_user.scalar_one_or_none()

            if user is None:
                user = UserOrm(
                    id=uuid.uuid4(),
                    external_id=template.user_id,
                    status="active",
                )
                session.add(user)
                await session.flush()
            elif user.status != "active":
                user.status = "active"

            # 2. Check for existing Template record
            stmt_tmpl = select(TemplateOrm).where(TemplateOrm.user_id == user.id)
            res_tmpl = await session.execute(stmt_tmpl)
            existing = res_tmpl.scalar_one_or_none()

            # 3. Encrypt embedding vector with AAD bound to user UUID and model version
            enc_rec = self.encryptor.encrypt(
                embedding=template.embedding,
                user_id=str(user.id),
                model_version=template.model_version,
            )

            now_utc = datetime.now(timezone.utc)

            if existing is not None:
                # Enforce optimistic concurrency control
                if expected_version is not None and existing.version != expected_version:
                    raise OptimisticLockError(
                        f"Optimistic lock conflict for user '{template.user_id}': "
                        f"expected version {expected_version}, but found {existing.version}."
                    )

                existing.template_id = template.template_id
                existing.model_version = template.model_version
                existing.encrypted_blob = enc_rec.encrypted_blob
                existing.key_id = enc_rec.key_id
                existing.nonce = enc_rec.nonce
                existing.wrapped_data_key = enc_rec.wrapped_data_key
                existing.format_version = enc_rec.format_version
                existing.frames_used = template.frames_used
                existing.metadata_json = template.metadata
                existing.version += 1
                existing.updated_at = now_utc
            else:
                new_tmpl = TemplateOrm(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    template_id=template.template_id,
                    model_version=template.model_version,
                    embedding_dim=512,
                    encrypted_blob=enc_rec.encrypted_blob,
                    key_id=enc_rec.key_id,
                    nonce=enc_rec.nonce,
                    wrapped_data_key=enc_rec.wrapped_data_key,
                    format_version=enc_rec.format_version,
                    frames_used=template.frames_used,
                    metadata_json=template.metadata,
                    version=1,
                    created_at=now_utc,
                    updated_at=now_utc,
                )
                session.add(new_tmpl)

    async def get_template(self, user_id: str) -> EnrolledTemplate | None:
        """Retrieves and decrypts a template for the specified user_id."""
        async with self.session_factory() as session:
            stmt = (
                select(UserOrm, TemplateOrm)
                .join(TemplateOrm, UserOrm.id == TemplateOrm.user_id)
                .where(UserOrm.external_id == user_id)
            )
            res = await session.execute(stmt)
            row = res.first()
            if not row:
                return None

            user, tmpl = row
            if user.status not in ("active", "needs_reenrollment"):
                return None

            enc_rec = EncryptedTemplateRecord(
                encrypted_blob=tmpl.encrypted_blob,
                wrapped_data_key=tmpl.wrapped_data_key,
                nonce=tmpl.nonce,
                key_id=tmpl.key_id,
                format_version=tmpl.format_version,
            )

            emb = self.encryptor.decrypt(
                record=enc_rec,
                user_id=str(user.id),
                model_version=tmpl.model_version,
            )

            return EnrolledTemplate(
                user_id=user.external_id,
                template_id=tmpl.template_id,
                embedding=emb,
                model_version=tmpl.model_version,
                enrolled_at_iso=tmpl.created_at.isoformat(),
                frames_used=tmpl.frames_used,
                metadata=tmpl.metadata_json,
            )

    async def delete_template(self, user_id: str) -> bool:
        """Permanently deletes the biometric template for user_id."""
        async with self.session_factory() as session, session.begin():
            stmt = (
                select(TemplateOrm)
                .join(UserOrm, TemplateOrm.user_id == UserOrm.id)
                .where(UserOrm.external_id == user_id)
            )
            res = await session.execute(stmt)
            tmpl = res.scalar_one_or_none()
            if tmpl is None:
                return False

            await session.delete(tmpl)
            return True

    async def delete_user_completely(self, user_id: str) -> bool:
        """
        Right-to-be-forgotten deletion:
        Atomically deletes templates, sessions, and user records,
        and anonymizes historical audit event references.
        """
        async with self.session_factory() as session, session.begin():
            stmt_user = select(UserOrm).where(UserOrm.external_id == user_id)
            res_user = await session.execute(stmt_user)
            user = res_user.scalar_one_or_none()
            if user is None:
                return False

            # Delete user (cascades to templates & enrollment_sessions, SET NULL on audit_events)
            await session.delete(user)
            return True

    async def list_templates(
        self, model_version: str | None = None
    ) -> list[EnrolledTemplate]:
        """
        Streams and decrypts all active templates using keyset pagination.
        Avoids high memory pressure when loading large galleries.
        """
        templates: list[EnrolledTemplate] = []
        last_id: uuid.UUID | None = None

        async with self.session_factory() as session:
            while True:
                stmt = (
                    select(TemplateOrm, UserOrm)
                    .join(UserOrm, TemplateOrm.user_id == UserOrm.id)
                    .where(UserOrm.status == "active")
                )
                if model_version:
                    stmt = stmt.where(TemplateOrm.model_version == model_version)
                if last_id is not None:
                    stmt = stmt.where(TemplateOrm.id > last_id)

                stmt = stmt.order_by(TemplateOrm.id).limit(self.batch_size)
                res = await session.execute(stmt)
                rows = res.all()
                if not rows:
                    break

                for tmpl, user in rows:
                    enc_rec = EncryptedTemplateRecord(
                        encrypted_blob=tmpl.encrypted_blob,
                        wrapped_data_key=tmpl.wrapped_data_key,
                        nonce=tmpl.nonce,
                        key_id=tmpl.key_id,
                        format_version=tmpl.format_version,
                    )
                    emb = self.encryptor.decrypt(
                        record=enc_rec,
                        user_id=str(user.id),
                        model_version=tmpl.model_version,
                    )
                    templates.append(
                        EnrolledTemplate(
                            user_id=user.external_id,
                            template_id=tmpl.template_id,
                            embedding=emb,
                            model_version=tmpl.model_version,
                            enrolled_at_iso=tmpl.created_at.isoformat(),
                            frames_used=tmpl.frames_used,
                            metadata=tmpl.metadata_json,
                        )
                    )

                last_id = rows[-1][0].id

        return templates

    async def count(self) -> int:
        """Returns total count of enrolled templates."""
        async with self.session_factory() as session:
            res = await session.execute(select(func.count()).select_from(TemplateOrm))
            return int(res.scalar_one())

    async def ping(self) -> bool:
        """Checks database connectivity."""
        try:
            async with self.session_factory() as session:
                await session.execute(text("SELECT 1"))
                return True
        except Exception:  # noqa: BLE001
            return False
