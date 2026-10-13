# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_model.py: Unit tests for IR_18_Partial neural network architecture.
"""

import torch

from freqid_core.model import IR_18_Partial


def test_model_instantiation():
    model = IR_18_Partial(input_channel=27, embedding_dim=512)
    param_count = sum(p.numel() for p in model.parameters())

    # IR_18 with 27-channel input layer has ~24.03M parameters
    assert 24_000_000 < param_count < 24_100_000
    assert model.input_layer[0].in_channels == 27
    assert model.input_layer[0].out_channels == 64


def test_model_forward_pass():
    model = IR_18_Partial(input_channel=27, embedding_dim=512)
    model.eval()

    dummy_input = torch.randn(2, 27, 112, 112, dtype=torch.float32)
    with torch.no_grad():
        out = model(dummy_input)

    assert out.shape == (2, 512)
    assert out.dtype == torch.float32
    assert torch.isfinite(out).all()
