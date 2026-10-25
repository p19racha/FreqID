# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
postgres.py: Asynchronous, bounded-queue PostgreSQL audit sink with optional hash chaining.
"""

from __future__ import annotations

import asyncio
import hashlib

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from freqid_server.audit.base import AuditEvent, AuditSink, hash_client_ip
from freqid_server.logging import logger
from freqid_server.storage.models import AuditEventOrm, UserOrm


class PostgresAuditSink(AuditSink):
    """
    Non-blocking, high-throughput PostgreSQL audit event sink.
    Decouples request handlers from database latency via a bounded in-memory buffer.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        max_queue_size: int = 10000,
        batch_size: int = 100,
        flush_interval_seconds: float = 0.5,
        enable_hash_chain: bool = False,
        ip_salt: str = "freqid_ip_salt",
    ) -> None:
        self.session_factory = session_factory
        self.max_queue_size = max_queue_size
        self.batch_size = batch_size
        self.flush_interval = flush_interval_seconds
        self.enable_hash_chain = enable_hash_chain
        self.ip_salt = ip_salt

        self._queue: asyncio.Queue[AuditEvent] = asyncio.Queue(maxsize=max_queue_size)
        self._worker_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._dropped_count = 0
        self._last_chain_hash: str | None = None

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    async def emit(self, event: AuditEvent) -> None:
        """Enqueues audit event immediately; never blocks the caller."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._dropped_count += 1
            logger.warning(
                f"Audit queue capacity ({self.max_queue_size}) exceeded! Dropped event "
                f"'{event.event_type}' (Total dropped: {self._dropped_count})"
            )

    async def start(self) -> None:
        """Starts background worker."""
        if self._worker_task is None or self._worker_task.done():
            self._stop_event.clear()
            self._worker_task = asyncio.create_task(self._worker_loop(), name="freqid-audit-worker")

    async def shutdown(self) -> None:
        """Flushes remaining queued events and terminates worker."""
        self._stop_event.set()
        if self._worker_task:
            await self._worker_task
            self._worker_task = None

        # Final drain to ensure zero lost events
        await self._flush_remaining()

    async def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._drain_batch()
                await asyncio.sleep(self.flush_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.error(f"Error in audit worker batch write: {e}", exc_info=True)
                await asyncio.sleep(1.0)

    async def _drain_batch(self) -> int:
        events: list[AuditEvent] = []
        while len(events) < self.batch_size:
            try:
                event = self._queue.get_nowait()
                events.append(event)
            except asyncio.QueueEmpty:
                break

        if not events:
            return 0

        await self._write_events_to_db(events)
        return len(events)

    async def _flush_remaining(self) -> None:
        events: list[AuditEvent] = []
        while not self._queue.empty():
            try:
                events.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        if events:
            await self._write_events_to_db(events)

    async def _write_events_to_db(self, events: list[AuditEvent]) -> None:
        async with self.session_factory() as session, session.begin():
            # 1. Resolve user UUIDs for any external_ids in batch
            external_ids = {e.user_external_id for e in events if e.user_external_id}
            user_id_map = {}
            if external_ids:
                stmt = select(UserOrm.id, UserOrm.external_id).where(
                    UserOrm.external_id.in_(external_ids)
                )
                res = await session.execute(stmt)
                user_id_map = {row.external_id: row.id for row in res.all()}

            # 2. Build row dicts
            rows = []
            for e in events:
                user_uuid = user_id_map.get(e.user_external_id) if e.user_external_id else None
                ext_id_hash = None
                if e.user_external_id:
                    ext_id_hash = hashlib.sha256(e.user_external_id.encode("utf-8")).hexdigest()

                ip_hash = hash_client_ip(e.client_ip, salt=self.ip_salt)

                chain_val = None
                if self.enable_hash_chain:
                    chain_input = (
                        f"{self._last_chain_hash or 'GENESIS'}:"
                        f"{e.event_time.isoformat()}:{e.event_type}:"
                        f"{e.principal_id}:{e.decision}:{e.request_id}"
                    )
                    chain_val = hashlib.sha256(chain_input.encode("utf-8")).hexdigest()
                    self._last_chain_hash = chain_val

                rows.append(
                    {
                        "id": e.event_id,
                        "event_time": e.event_time,
                        "event_type": e.event_type,
                        "principal_type": e.principal_type,
                        "principal_id": e.principal_id,
                        "device_id": e.device_id,
                        "admin_id": e.admin_id,
                        "user_id": user_uuid,
                        "user_external_id_hash": ext_id_hash,
                        "decision": e.decision,
                        "score_bucket": e.score_bucket,
                        "request_id": e.request_id,
                        "model_version": e.model_version,
                        "client_ip_hash": ip_hash,
                        "chain_hash": chain_val,
                    }
                )

            await session.execute(insert(AuditEventOrm).values(rows))
