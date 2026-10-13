# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_export_onnx.py: Unit tests for ONNX export and verification routines.
"""

import os

from freqid_core.export_onnx import export_to_onnx, verify_onnx_export
from freqid_core.model import IR_18_Partial


def test_export_and_verify_onnx(tmp_path):
    model = IR_18_Partial(input_channel=27, embedding_dim=512)
    model.eval()

    onnx_file = str(tmp_path / "test_model.onnx")
    out_path = export_to_onnx(model, onnx_file, opset_version=14, dynamic_batch=True)

    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 10_000_000

    max_diff = verify_onnx_export(model, out_path, atol=1e-4)
    assert max_diff < 1e-4
