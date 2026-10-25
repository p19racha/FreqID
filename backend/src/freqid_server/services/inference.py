# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
inference.py: Thread-safe forward embedding service with bounded queue and load shedding.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import freqid_core as fq
import numpy as np
from freqid_core.embedder import Embedder, ModelInfo

from freqid_server.config import ServerConfig
from freqid_server.errors import (
    InferenceQueueFullError,
    InferenceTimeoutError,
    ModelVersionMismatchError,
)
from freqid_server.logging import logger


class InferenceService:
    """
    Manages the deep neural network embedder session.
    Runs inference off the asyncio event loop using a dedicated ThreadPoolExecutor.
    """

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self._embedder: Embedder | None = None
        self._pool: ThreadPoolExecutor | None = None
        self._queue_semaphore: asyncio.Semaphore | None = None
        self._model_info: ModelInfo | None = None

    def start(self) -> None:
        """Initializes the embedder session and thread pool. Called once during lifespan startup."""
        logger.info(
            f"Loading PartialFace embedder from checkpoint: {self.config.model_path} "
            f"(backend: {self.config.model_backend}, device: {self.config.device})"
        )
        self._embedder = Embedder.from_checkpoint(
            ckpt_path=self.config.model_path,
            backend=self.config.model_backend,
            device=self.config.device,
        )
        self._model_info = self._embedder.model_info()
        self._pool = ThreadPoolExecutor(
            max_workers=self.config.max_inference_workers,
            thread_name_prefix="freqid-infer-worker",
        )
        self._queue_semaphore = asyncio.Semaphore(self.config.max_queue_size)
        logger.info(
            f"Embedder successfully initialized. Checkpoint SHA-256: {self._model_info.checkpoint_hash[:12]}..., "
            f"Embedding dim: {self._model_info.embedding_dim}, Input shape: {self._model_info.input_shape}"
        )

    def shutdown(self) -> None:
        """Gracefully shuts down thread pool workers. Called during lifespan shutdown."""
        if self._pool:
            logger.info("Shutting down inference thread pool...")
            self._pool.shutdown(wait=True)
            self._pool = None
        self._embedder = None

    @property
    def model_info(self) -> ModelInfo:
        if self._model_info is None:
            raise RuntimeError("InferenceService has not been started.")
        return self._model_info

    @property
    def checkpoint_sha256(self) -> str:
        return self.model_info.checkpoint_hash

    @property
    def backend(self) -> str:
        return self.config.model_backend

    @property
    def device(self) -> str:
        return self.config.device

    @property
    def is_ready(self) -> bool:
        return self._embedder is not None and self._pool is not None

    async def embed(self, payload: fq.PartialFacePayload) -> np.ndarray:
        """
        Embeds a single PartialFacePayload into a 512-D L2-normalized float32 embedding vector.

        Validates queue capacity, runs inference off-thread, and enforces timeout budget.
        """
        if (
            not self.is_ready
            or self._embedder is None
            or self._pool is None
            or self._queue_semaphore is None
        ):
            raise RuntimeError("Inference service is not initialized or ready.")

        # Check payload metadata compatibility
        if hasattr(payload, "version") and payload.version != 1:
            raise ModelVersionMismatchError(
                f"Payload wire format version {payload.version} is incompatible with server version 1."
            )

        # Bounded queue overload protection
        if self._queue_semaphore.locked():
            raise InferenceQueueFullError(
                "Server inference queue is saturated. Please retry.", retry_after=1
            )
        await self._queue_semaphore.acquire()

        try:
            loop = asyncio.get_running_loop()
            task = loop.run_in_executor(self._pool, self._embedder.embed, payload)
            embedding: np.ndarray = await asyncio.wait_for(
                task, timeout=self.config.inference_timeout_seconds
            )
            return embedding
        except asyncio.TimeoutError:
            raise InferenceTimeoutError(
                f"Inference execution exceeded timeout budget ({self.config.inference_timeout_seconds}s)."
            )
        finally:
            self._queue_semaphore.release()
