# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
embedder.py: Inference embedder supporting PyTorch and ONNX Runtime backends.

CRITICAL PRIVACY BOUNDARY:
This class accepts ONLY 27-channel partial frequency representations.
Passing a 3-channel raw image is strictly prohibited and rejected by shape validation.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import torch

from freqid_core.config import ModelConfig
from freqid_core.errors import (
    BackendNotAvailableError,
    CheckpointLoadError,
    ShapeMismatchError,
)
from freqid_core.model import IR_18_Partial
from freqid_core.payload import PartialFacePayload


@dataclass(frozen=True)
class ModelInfo:
    """Metadata describing the loaded model and inference environment."""

    backbone: str
    backend: str
    device: str
    input_shape: tuple[int, int, int]
    embedding_dim: int
    param_count: int
    checkpoint_hash: str


def _compute_file_sha256(filepath: str) -> str:
    """Computes SHA-256 hash of a checkpoint file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


class Embedder:
    """
    Extracts L2-normalized 512-D identity embeddings from 27-channel partial frequency inputs.
    """

    def __init__(
        self,
        backend: Literal["torch", "onnx"],
        device: str,
        config: ModelConfig,
        model_instance: Any,
        checkpoint_hash: str,
    ) -> None:
        self._backend = backend
        self._device = device
        self._config = config
        self._model = model_instance
        self._checkpoint_hash = checkpoint_hash

    @classmethod
    def from_checkpoint(
        cls,
        ckpt_path: str,
        backend: Literal["torch", "onnx"] = "torch",
        device: str = "cpu",
        config: ModelConfig | None = None,
    ) -> Embedder:
        """
        Loads weights from a PyTorch (.pth) or ONNX (.onnx) file.

        Args:
            ckpt_path: Path to checkpoint file.
            backend: "torch" or "onnx".
            device: Execution device ("cpu" or "cuda").
            config: Optional model configuration.

        Raises:
            CheckpointLoadError: If file not found, keys missing, or format invalid.
            BackendNotAvailableError: If requested backend is not installed.
        """
        if not os.path.isfile(ckpt_path):
            raise CheckpointLoadError(f"Checkpoint file not found: {ckpt_path}")

        cfg = config or ModelConfig()
        ckpt_hash = _compute_file_sha256(ckpt_path)

        # Device fallback check
        resolved_device = device
        if "cuda" in resolved_device and not torch.cuda.is_available():
            resolved_device = "cpu"

        if backend == "torch":
            try:
                ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
            except Exception as e:
                raise CheckpointLoadError(f"Failed to load PyTorch checkpoint: {e}") from e

            # Extract backbone state dict
            if isinstance(ckpt, dict):
                if "backbone" in ckpt:
                    state_dict = ckpt["backbone"]
                elif "model" in ckpt:
                    state_dict = ckpt["model"]
                elif "state_dict" in ckpt:
                    state_dict = ckpt["state_dict"]
                else:
                    state_dict = ckpt
            else:
                state_dict = ckpt

            # Strip prefixes like "module." (from DDP) or "backbone."
            cleaned_state_dict: dict[str, Any] = {}
            for k, v in state_dict.items():
                name = k
                name = name.removeprefix("module.")
                name = name.removeprefix("backbone.")
                cleaned_state_dict[name] = v

            model = IR_18_Partial(
                input_channel=cfg.input_channels,
                embedding_dim=cfg.embedding_dim,
                spatial_size=cfg.spatial_size,
            )

            # Load strictly and report any discrepancies
            try:
                missing, unexpected = model.load_state_dict(cleaned_state_dict, strict=True)
                if missing:
                    raise CheckpointLoadError(f"Missing keys in state dict: {missing}")
                if unexpected:
                    raise CheckpointLoadError(f"Unexpected keys in state dict: {unexpected}")
            except RuntimeError as e:
                raise CheckpointLoadError(
                    f"State dict mismatch when loading {ckpt_path}: {e}"
                ) from e

            model.to(resolved_device)
            model.eval()

            return cls(
                backend="torch",
                device=resolved_device,
                config=cfg,
                model_instance=model,
                checkpoint_hash=ckpt_hash,
            )

        elif backend == "onnx":
            try:
                import onnxruntime as ort
            except ImportError as e:
                raise BackendNotAvailableError(
                    "onnxruntime is not installed. Install via pip install freqid-core[onnx]"
                ) from e

            providers = (
                ["CUDAExecutionProvider", "CPUExecutionProvider"]
                if "cuda" in resolved_device
                else ["CPUExecutionProvider"]
            )
            session = ort.InferenceSession(ckpt_path, providers=providers)
            active_device = "cuda" if "CUDAExecutionProvider" in session.get_providers() else "cpu"

            return cls(
                backend="onnx",
                device=active_device,
                config=cfg,
                model_instance=session,
                checkpoint_hash=ckpt_hash,
            )

        else:
            raise ValueError(f"Unsupported backend {backend!r}. Must be 'torch' or 'onnx'.")

    def embed(
        self,
        input_data: PartialFacePayload | np.ndarray | torch.Tensor,
    ) -> np.ndarray:
        """
        Computes L2-normalized 512-D embeddings.

        Args:
            input_data: PartialFacePayload, NumPy array, or Torch tensor.
                        Expected shape: (27, 112, 112) or (B, 27, 112, 112), dtype float32.

        Returns:
            NumPy array of shape (512,) if single input, or (B, 512) if batch.
            Embeddings are unit-normalized: ||e||_2 == 1.0.
        """
        is_single = False
        if isinstance(input_data, PartialFacePayload):
            arr = input_data.batch_data
            is_single = input_data.batch_size == 1 and input_data.shape == (27, 112, 112)
        elif isinstance(input_data, np.ndarray):
            if input_data.ndim == 3:
                if input_data.shape != (27, 112, 112):
                    raise ShapeMismatchError(
                        f"Expected partial frequency shape (27, 112, 112), got {input_data.shape}. "
                        "Raw 3-channel images cannot be processed by Embedder."
                    )
                arr = np.ascontiguousarray(input_data[np.newaxis, ...], dtype=np.float32)
                is_single = True
            elif input_data.ndim == 4:
                if input_data.shape[1:] != (27, 112, 112):
                    raise ShapeMismatchError(
                        f"Expected partial frequency shape (B, 27, 112, 112), got {input_data.shape}. "
                        "Raw 3-channel images cannot be processed by Embedder."
                    )
                arr = np.ascontiguousarray(input_data, dtype=np.float32)
            else:
                raise ShapeMismatchError(f"Unsupported input dimension {input_data.ndim}D")
        elif isinstance(input_data, torch.Tensor):
            if input_data.ndim == 3:
                if input_data.shape != (27, 112, 112):
                    raise ShapeMismatchError(
                        f"Expected partial frequency shape (27, 112, 112), got {input_data.shape}."
                    )
                arr = input_data.unsqueeze(0).detach().cpu().numpy().astype(np.float32)
                is_single = True
            elif input_data.ndim == 4:
                if input_data.shape[1:] != (27, 112, 112):
                    raise ShapeMismatchError(
                        f"Expected partial frequency shape (B, 27, 112, 112), got {input_data.shape}."
                    )
                arr = input_data.detach().cpu().numpy().astype(np.float32)
            else:
                raise ShapeMismatchError(f"Unsupported tensor dimension {input_data.ndim}D")
        else:
            raise TypeError(f"Unsupported input type {type(input_data).__name__}")

        # Execute inference
        if self._backend == "torch":
            tensor = torch.from_numpy(arr).to(self._device)
            with torch.inference_mode():
                raw_emb = self._model(tensor)  # (B, 512)
                # L2 unit normalization
                norm_emb = raw_emb / torch.norm(raw_emb, p=2, dim=1, keepdim=True)
                emb_np = norm_emb.cpu().numpy().astype(np.float32)
        elif self._backend == "onnx":
            input_name = self._model.get_inputs()[0].name
            raw_emb = self._model.run(None, {input_name: arr})[0]  # (B, 512)
            # L2 unit normalization
            norms = np.linalg.norm(raw_emb, axis=1, keepdims=True)
            norms = np.maximum(norms, 1e-12)
            emb_np = (raw_emb / norms).astype(np.float32)
        else:
            raise RuntimeError(f"Unknown backend {self._backend}")

        return emb_np[0] if is_single else emb_np

    def model_info(self) -> ModelInfo:
        """Returns model architecture, parameter count, device, and checkpoint checksum."""
        if self._backend == "torch":
            param_count = sum(p.numel() for p in self._model.parameters())
        else:
            param_count = 0  # Not directly inspectable in serialized ONNX session

        return ModelInfo(
            backbone=self._config.backbone,
            backend=self._backend,
            device=self._device,
            input_shape=(self._config.input_channels, *self._config.spatial_size),
            embedding_dim=self._config.embedding_dim,
            param_count=param_count,
            checkpoint_hash=self._checkpoint_hash,
        )
