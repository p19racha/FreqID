# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
export_onnx.py: Export PartialFace PyTorch backbone to standard ONNX format.

Pins opset 14 for optimal broad compatibility across server runtimes (ONNX Runtime,
TensorRT, OpenVINO) and edge WASM targets without deprecated operator schemas.
"""

from __future__ import annotations

import os

import numpy as np
import torch
from torch import nn

try:
    import onnx
    import onnxruntime as ort
    HAS_ONNX = True
except ImportError:
    HAS_ONNX = False

from freqid_core.errors import BackendNotAvailableError


def export_to_onnx(
    model: nn.Module,
    output_path: str,
    opset_version: int = 14,
    dynamic_batch: bool = True,
    sample_input_shape: tuple[int, int, int, int] = (1, 27, 112, 112),
) -> str:
    """
    Exports a PyTorch PartialFace backbone to an ONNX model file.

    Args:
        model: PyTorch backbone in eval mode.
        output_path: Target .onnx file path.
        opset_version: Pinned ONNX opset version (default: 14).
        dynamic_batch: If True, marks batch dimension as dynamic.
        sample_input_shape: Shape of dummy input tensor.

    Returns:
        Absolute path to exported ONNX file.
    """
    if not HAS_ONNX:
        raise BackendNotAvailableError("onnx and onnxruntime are required for ONNX export.")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    model.eval()

    device = next(model.parameters()).device
    dummy_input = torch.randn(*sample_input_shape, dtype=torch.float32, device=device)

    dynamic_axes: dict[str, dict[int, str]] = {}
    if dynamic_batch:
        dynamic_axes = {
            "partial_frequency": {0: "batch_size"},
            "embedding": {0: "batch_size"},
        }

    torch.onnx.export(
        model,
        (dummy_input,),
        output_path,
        export_params=True,
        opset_version=opset_version,
        do_constant_folding=True,
        input_names=["partial_frequency"],
        output_names=["embedding"],
        dynamic_axes=dynamic_axes if dynamic_batch else None,
    )

    # Validate ONNX graph integrity
    onnx_model = onnx.load(output_path)
    onnx.checker.check_model(onnx_model)

    return os.path.abspath(output_path)


def verify_onnx_export(
    torch_model: nn.Module,
    onnx_path: str,
    atol: float = 1e-4,
) -> float:
    """
    Compares outputs between PyTorch and ONNX Runtime to verify mathematical equivalence.

    Returns:
        Maximum absolute error between unit-normalized embeddings.
    """
    if not HAS_ONNX:
        raise BackendNotAvailableError("onnxruntime is required for verification.")

    torch_model.eval()
    device = next(torch_model.parameters()).device

    session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name

    max_diff = 0.0
    for batch_size in (1, 4):
        test_input_np = np.random.randn(batch_size, 27, 112, 112).astype(np.float32)
        test_input_torch = torch.from_numpy(test_input_np).to(device)

        # PyTorch forward
        with torch.inference_mode():
            torch_out = torch_model(test_input_torch)
            torch_norm = torch_out / torch.norm(torch_out, p=2, dim=1, keepdim=True)
            torch_emb = torch_norm.cpu().numpy()

        # ONNX Runtime forward
        onnx_out = session.run(None, {input_name: test_input_np})[0]
        onnx_norm = onnx_out / np.linalg.norm(onnx_out, axis=1, keepdims=True)

        diff = float(np.max(np.abs(torch_emb - onnx_norm)))
        max_diff = max(max_diff, diff)

        assert diff < atol, f"ONNX verification failed: max diff {diff:.2e} >= {atol:.2e}"

    return max_diff
