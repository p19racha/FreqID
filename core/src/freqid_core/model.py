# Copyright 2026 FreqID Authors. Apache-2.0 License.
#
# Derivative work based on Tencent/TFace:
# Original source: recognition/torchkit/backbone/model_irse.py
# Upstream commit: 171ec14562098d5c416e6d1bb90cfaf53b4ae12e
# Original authors: Tencent/TFace contributors (based on ZhaoJ9014/face.evoLVe.PyTorch)
# Licensed under the Apache License, Version 2.0.
"""
model.py: Inference-only implementation of PartialFace IR_18 backbone.

This module contains only the neural network architecture required for inference.
It strips all training heads (ArcFace, CosFace), distributed wrappers, and loss functions.
"""

from collections import namedtuple

import torch
from torch import nn

Bottleneck = namedtuple("Bottleneck", ["in_channel", "depth", "stride"])


class BasicBlockIR(nn.Module):
    """Basic residual block for Improved ResNet (IRNet)."""

    def __init__(self, in_channel: int, depth: int, stride: int) -> None:
        super().__init__()
        self.shortcut_layer: nn.Module
        if in_channel == depth:
            self.shortcut_layer = nn.MaxPool2d(1, stride)
        else:
            self.shortcut_layer = nn.Sequential(
                nn.Conv2d(in_channel, depth, (1, 1), stride, bias=False),
                nn.BatchNorm2d(depth),
            )
        self.res_layer = nn.Sequential(
            nn.BatchNorm2d(in_channel),
            nn.Conv2d(in_channel, depth, (3, 3), (1, 1), 1, bias=False),
            nn.BatchNorm2d(depth),
            nn.PReLU(depth),
            nn.Conv2d(depth, depth, (3, 3), stride, 1, bias=False),
            nn.BatchNorm2d(depth),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        shortcut = self.shortcut_layer(x)
        res = self.res_layer(x)
        return res + shortcut


def _get_block(in_channel: int, depth: int, num_units: int, stride: int = 2) -> list[Bottleneck]:
    return [Bottleneck(in_channel, depth, stride)] + [
        Bottleneck(depth, depth, 1) for _ in range(num_units - 1)
    ]


def _get_ir18_blocks() -> list[list[Bottleneck]]:
    """Returns the 4 stages of IR_18 (units: [2, 2, 2, 2])."""
    return [
        _get_block(in_channel=64, depth=64, num_units=2),
        _get_block(in_channel=64, depth=128, num_units=2),
        _get_block(in_channel=128, depth=256, num_units=2),
        _get_block(in_channel=256, depth=512, num_units=2),
    ]


class IR_18_Partial(nn.Module):
    """
    Inference-only Improved ResNet-18 modified for PartialFace 27-channel inputs.
    """

    def __init__(
        self,
        input_channel: int = 27,
        embedding_dim: int = 512,
        spatial_size: tuple[int, int] = (112, 112),
    ) -> None:
        super().__init__()
        assert spatial_size[0] == 112, f"Only 112x112 input is supported, got {spatial_size}"

        self.input_layer = nn.Sequential(
            nn.Conv2d(input_channel, 64, (3, 3), 1, 1, bias=False),
            nn.BatchNorm2d(64),
            nn.PReLU(64),
        )

        blocks = _get_ir18_blocks()
        modules: list[nn.Module] = []
        for stage in blocks:
            for b in stage:
                modules.append(BasicBlockIR(b.in_channel, b.depth, b.stride))
        self.body = nn.Sequential(*modules)

        # Output projection to embedding_dim with standardizing BatchNorm
        self.output_layer = nn.Sequential(
            nn.BatchNorm2d(512),
            nn.Dropout(0.4),  # Identity in eval mode
            nn.Flatten(),
            nn.Linear(512 * 7 * 7, embedding_dim),
            nn.BatchNorm1d(embedding_dim, affine=False),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass.
        Args:
            x: Input tensor of shape (B, 27, 112, 112), dtype float32.
        Returns:
            Pre-normalized 512-D feature vector of shape (B, 512).
        """
        x = self.input_layer(x)
        x = self.body(x)
        x = self.output_layer(x)
        return x
