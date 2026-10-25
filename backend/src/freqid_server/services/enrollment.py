# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
enrollment.py: Multi-sample enrollment coordinator, outlier rejection, and template synthesis.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import freqid_core as fq
import numpy as np

from freqid_server.audit.base import AuditEvent, AuditSink, coarse_score_bucket
from freqid_server.config import ServerConfig
from freqid_server.errors import (
    DuplicateIdentityError,
    InvalidPayloadError,
    StorageError,
    UserNotFoundError,
)
from freqid_server.logging import logger
from freqid_server.services.gallery import GalleryIndex
from freqid_server.services.inference import InferenceService
from freqid_server.storage.base import EnrolledTemplate, TemplateStore


class EnrollmentService:
    """Coordinates parsing of multi-sample enrollment payloads, outlier pruning, and template storage."""

    def __init__(
        self,
        config: ServerConfig,
        inference_service: InferenceService,
        store: TemplateStore,
        gallery: GalleryIndex,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self.config = config
        self.inference = inference_service
        self.store = store
        self.gallery = gallery
        self.audit_sink = audit_sink

    @staticmethod
    def pack_framed_payloads(payloads: list[fq.PartialFacePayload]) -> bytes:
        """Packs a list of PartialFacePayloads into a binary stream with 4-byte big-endian length headers."""
        chunks: list[bytes] = []
        for p in payloads:
            raw = p.to_bytes()
            chunks.append(len(raw).to_bytes(4, byteorder="big"))
            chunks.append(raw)
        return b"".join(chunks)

    @staticmethod
    def unpack_framed_payloads(
        packed_bytes: bytes, max_frames: int = 10
    ) -> list[fq.PartialFacePayload]:
        """Unpacks multi-payload binary stream with 4-byte big-endian length headers."""
        payloads: list[fq.PartialFacePayload] = []
        offset = 0
        total_len = len(packed_bytes)

        while offset < total_len:
            if offset + 4 > total_len:
                break
            p_len = int.from_bytes(packed_bytes[offset : offset + 4], byteorder="big")
            offset += 4

            if offset + p_len > total_len:
                raise InvalidPayloadError(
                    f"Framed payload truncated: header specifies {p_len} bytes, but only {total_len - offset} remain."
                )

            chunk = packed_bytes[offset : offset + p_len]
            offset += p_len

            try:
                payload = fq.PartialFacePayload.from_bytes(chunk)
                payloads.append(payload)
            except Exception as e:
                raise InvalidPayloadError(f"Failed to decode framed enrollment payload: {e}") from e

            if len(payloads) > max_frames:
                raise InvalidPayloadError(
                    f"Exceeded maximum permitted enrollment frames ({max_frames})."
                )

        if not payloads:
            raise InvalidPayloadError(
                "No valid PartialFacePayload frames found in enrollment stream."
            )

        return payloads

    async def enroll_user(
        self,
        user_id: str,
        payloads: list[fq.PartialFacePayload],
        metadata: dict[str, Any] | None = None,
        is_re_enroll: bool = False,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """
        Embeds sample payloads, removes outliers, synthesizes template, and updates store + gallery.
        Enforces capacity limits, duplicate checking, and failure-safe atomic ordering.
        """
        if not payloads:
            raise InvalidPayloadError("Enrollment requires at least one payload.")

        # 1. Capacity limit guardrail
        current_count = await self.store.count()
        existing_template = await self.store.get_template(user_id)

        if existing_template is None and current_count >= self.config.max_enrolled_users:
            raise StorageError(
                f"Maximum enrolled identity capacity ({self.config.max_enrolled_users}) reached."
            )

        # 2. Accidental overwrite check: must explicitly set is_re_enroll to replace template
        if existing_template is not None and not is_re_enroll:
            raise DuplicateIdentityError(
                f"User '{user_id}' is already enrolled. Pass re_enroll=true or X-Re-Enroll: true header to replace."
            )

        # 3. Forward inference for each sample
        embs: list[np.ndarray] = []
        for p in payloads:
            emb = await self.inference.embed(p)
            embs.append(emb)

        # 4. Outlier rejection (for batches of 3 or more samples)
        accepted_embs = list(embs)
        outliers_count = 0
        quality_score = 0.95

        if len(embs) >= 3:
            filtered_embs = []
            mean_sims = []
            for i, target_e in enumerate(embs):
                other_embs = [e for j, e in enumerate(embs) if j != i]
                sims = [float(fq.cosine_similarity(target_e, o_e)) for o_e in other_embs]
                mean_sim = float(np.mean(sims))

                if mean_sim >= self.config.enroll_outlier_threshold:
                    filtered_embs.append(target_e)
                    mean_sims.append(mean_sim)
                else:
                    outliers_count += 1
                    logger.warning(
                        f"Pruned outlier sample during enrollment for user '{user_id}' "
                        f"(mean similarity: {mean_sim:.3f})"
                    )

            if not filtered_embs:
                raise InvalidPayloadError(
                    "Enrollment rejected: sample frames are too inconsistent to construct a reliable template."
                )

            accepted_embs = filtered_embs
            if mean_sims:
                quality_score = float(np.mean(mean_sims))

        # 5. Average and L2-normalize template vector
        avg_emb = np.mean(accepted_embs, axis=0)
        norm = np.linalg.norm(avg_emb)
        if norm > 0:
            avg_emb = (avg_emb / norm).astype(np.float32)

        # 6. Duplicate face check against existing gallery
        duplicate_warning: str | None = None
        if self.config.enroll_duplicate_check_policy != "disabled" and self.gallery.count > 0:
            dup_matches = self.gallery.search(
                query_embedding=avg_emb,
                top_k=1,
                threshold=self.config.enroll_duplicate_threshold,
                score_floor=self.config.enroll_duplicate_threshold,
            )
            if dup_matches and dup_matches[0].target_id != user_id:
                dup_id = dup_matches[0].target_id
                if self.config.enroll_duplicate_check_policy == "block":
                    raise DuplicateIdentityError(
                        f"Duplicate biometric face detected: matches existing enrolled identity '{dup_id}'."
                    )
                logger.warning(
                    f"Duplicate face detected for user '{user_id}': matches '{dup_id}' "
                    f"with similarity {dup_matches[0].similarity:.3f}"
                )
                duplicate_warning = f"Possible duplicate of '{dup_id}'"

        # 7. Construct template record
        template_id = f"tmpl_{user_id}_{int(time.time() * 1000)}"
        now_iso = datetime.now(timezone.utc).isoformat()
        template = EnrolledTemplate(
            user_id=user_id,
            template_id=template_id,
            embedding=avg_emb,
            model_version=self.config.model_version,
            enrolled_at_iso=now_iso,
            frames_used=len(accepted_embs),
            metadata=metadata or {},
        )

        # 8. Persist to storage FIRST (fail-safe: gallery is only updated if store write succeeds)
        await self.store.put_template(template, expected_version=expected_version)
        await self.gallery.add_or_update(user_id=user_id, embedding=avg_emb)

        # 9. Asynchronous audit event write
        if self.audit_sink:
            req_meta = metadata or {}
            event = AuditEvent(
                event_type="re_enroll" if is_re_enroll else "enroll",
                principal_type=req_meta.get("principal_type", "device"),
                principal_id=req_meta.get("principal_id"),
                device_id=req_meta.get("device_id"),
                user_external_id=user_id,
                decision="match",
                score_bucket=coarse_score_bucket(quality_score),
                request_id=req_meta.get("request_id", "unknown"),
                model_version=self.config.model_version,
            )
            await self.audit_sink.emit(event)

        logger.info(
            f"Successfully enrolled user '{user_id}' (Template: {template_id}, "
            f"Frames used: {len(accepted_embs)}/{len(payloads)})"
        )

        return {
            "status": "enrolled",
            "user_id": user_id,
            "template_id": template_id,
            "frames_processed": len(payloads),
            "frames_accepted": len(accepted_embs),
            "outliers_rejected": outliers_count,
            "quality_score": round(quality_score, 4),
            "duplicate_warning": duplicate_warning,
        }

    async def disable_user(self, user_id: str) -> None:
        """Disables an enrolled user and evicts identity from in-memory matching gallery."""
        existing = await self.store.get_template(user_id)
        if not existing:
            raise UserNotFoundError(f"User '{user_id}' not found.")

        # Evict from in-memory search gallery
        await self.gallery.remove(user_id)

    async def enable_user(self, user_id: str) -> None:
        """Re-enables a disabled user and restores identity to in-memory matching gallery."""
        existing = await self.store.get_template(user_id)
        if not existing:
            raise UserNotFoundError(f"User '{user_id}' not found.")

        # Re-add to in-memory search gallery
        await self.gallery.add_or_update(user_id=user_id, embedding=existing.embedding)
