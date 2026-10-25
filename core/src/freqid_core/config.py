# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
config.py: Dataclasses for transform, backbone model, and inference runtime configuration.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TransformConfig:
    """Configuration for client-side frequency transform, pruning, and sampling."""

    image_size: tuple[int, int] = (112, 112)
    ratio: int = 8
    block_size: int = 8
    stride: int = 8
    pruned_channels: tuple[int, ...] = (0, 1, 2, 3, 8, 9, 10, 16, 17, 24)
    num_subsets: int = 6
    channels_per_subset: int = 9

    @property
    def total_frequency_channels(self) -> int:
        """Total BDCT channels per color plane before pruning."""
        return self.block_size * self.block_size

    @property
    def kept_frequency_channels(self) -> int:
        """Total high-frequency channels retained after pruning."""
        return self.total_frequency_channels - len(self.pruned_channels)

    @property
    def model_input_channels(self) -> int:
        """Total channels fed to backbone: 3 color planes * channels_per_subset."""
        return 3 * self.channels_per_subset


@dataclass(frozen=True)
class ModelConfig:
    """Configuration for PartialFace backbone model."""

    backbone: str = "IR_18"
    input_channels: int = 27
    embedding_dim: int = 512
    spatial_size: tuple[int, int] = (112, 112)


@dataclass(frozen=True)
class InferenceConfig:
    """Runtime configuration for inference execution."""

    backend: str = "torch"
    device: str = "cpu"
    batch_size: int = 32
    fp16: bool = False
