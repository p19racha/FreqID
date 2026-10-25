# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
conftest.py: Shared fixtures and model checkpoint setup for freqid-core tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def ensure_core_test_checkpoints():
    """Generates synthetic IR_18 checkpoints if missing so embedder tests can run."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    ckpt_dir = repo_root / "research" / "outputs" / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = ckpt_dir / "partialface_ir_18.onnx"
    pth_path = ckpt_dir / "partialface_ir_18_epoch5.pth"

    if onnx_path.exists() and pth_path.exists():
        return

    try:
        import torch
        from freqid_core.export_onnx import export_to_onnx
        from freqid_core.model import IR_18_Partial

        torch.manual_seed(42)
        model = IR_18_Partial(input_channel=27, embedding_dim=512)
        model.eval()

        if not pth_path.exists():
            torch.save({"backbone": model.state_dict()}, str(pth_path))
        if not onnx_path.exists():
            export_to_onnx(model, str(onnx_path), opset_version=14, dynamic_batch=True)
    except Exception:
        pass
