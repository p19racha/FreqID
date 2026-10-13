# Copyright 2026 FreqID Authors. Apache-2.0 License.
#
# Derivative work based on Tencent/TFace:
# Original source: recognition/tasks/partialface/utils.py
# Upstream commit: 171ec14562098d5c416e6d1bb90cfaf53b4ae12e
# Original authors: Tencent/TFace contributors (ICCV 2023 PartialFace)
# Licensed under the Apache License, Version 2.0.
"""
transform.py: Client-side frequency transform, low-frequency pruning, and subset sampling.

CRITICAL PRIVACY BOUNDARY:
This module contains the ONLY code path in FreqID capable of ingesting raw spatial face images.
It is compiled and deployed strictly on edge client devices (Phase 3).
The central server (Phase 4) MUST NEVER import this module or any image decoding libraries.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence

import numpy as np
import torch
import torch.nn.functional as F
from torchjpeg import dct

from freqid_core.config import TransformConfig
from freqid_core.errors import ShapeMismatchError

# Fixed subset selection matrix S from ICCV 2023 PartialFace
# Maps 54 retained high-frequency channels into 6 non-overlapping subsets of 9 channels each.
SUBSET_SELECTION_MATRIX = torch.tensor(
    [
        [1, 24, 28, 12, 32, 45, 47, 40, 52],
        [35, 39, 44, 42, 10, 4, 37, 31, 53],
        [0, 50, 19, 6, 22, 51, 49, 23, 21],
        [38, 8, 25, 13, 17, 30, 7, 33, 9],
        [26, 29, 16, 2, 43, 14, 5, 11, 48],
        [36, 41, 46, 34, 15, 27, 18, 20, 3],
    ],
    dtype=torch.long,
)

# Candidate permutations P from PartialFace
# Applied to the 9 channels of each color plane to prevent position-based inversion attacks.
CANDIDATE_PERMUTATIONS = torch.tensor(
    [
        [0, 1, 2, 3, 4, 5, 6, 7, 8],
        [7, 3, 0, 6, 5, 4, 1, 2, 8],
        [4, 8, 6, 0, 2, 5, 3, 7, 1],
    ],
    dtype=torch.long,
)


def _preprocess_spatial_input(image: np.ndarray | torch.Tensor) -> torch.Tensor:
    """
    Standardize raw spatial image into a normalized PyTorch tensor in [-1, 1].

    Accepts:
    - NumPy uint8 array of shape (112, 112, 3) in RGB order [0..255]
    - NumPy float32 array of shape (3, 112, 112) in [-1, 1]
    - PyTorch float32 tensor of shape (3, 112, 112) or (1, 3, 112, 112) in [-1, 1]
    """
    if isinstance(image, np.ndarray):
        if image.ndim == 3 and image.shape == (112, 112, 3):
            # (H, W, C) uint8 RGB
            if image.dtype == np.uint8:
                tensor = torch.from_numpy(image.transpose((2, 0, 1))).float()
                tensor = (tensor / 255.0 - 0.5) / 0.5  # Map [0, 255] -> [-1, 1]
            else:
                tensor = torch.from_numpy(image.transpose((2, 0, 1))).float()
        elif image.ndim == 3 and image.shape == (3, 112, 112) or image.ndim == 4 and image.shape[1:] == (3, 112, 112):
            tensor = torch.from_numpy(image).float()
            if tensor.max() > 1.0 or tensor.min() < -1.0:
                tensor = (tensor / 255.0 - 0.5) / 0.5
        else:
            raise ShapeMismatchError(
                f"Unsupported image shape {image.shape}. Expected (112, 112, 3) or (3, 112, 112)."
            )
    elif isinstance(image, torch.Tensor):
        if image.ndim == 3 and image.shape == (3, 112, 112) or image.ndim == 4 and image.shape[1:] == (3, 112, 112):
            tensor = image.float()
        else:
            raise ShapeMismatchError(
                f"Unsupported tensor shape {image.shape}. Expected (3, 112, 112) or (B, 3, 112, 112)."
            )
    else:
        raise TypeError(f"Expected numpy.ndarray or torch.Tensor, got {type(image).__name__}")

    if tensor.ndim == 3:
        tensor = tensor.unsqueeze(0)

    return tensor


def raw_bdct_transform(
    x: torch.Tensor,
    config: TransformConfig | None = None,
) -> torch.Tensor:
    """
    Computes 8x8 Block Discrete Cosine Transform (BDCT) and prunes human-perceivable low frequencies.

    Preprocessing sequence:
    1. Rescale [-1, 1] -> [0, 1] (TorchJPEG expected range).
    2. Bilinear upsample with ratio=8 (align_corners=True) to 896x896.
    3. Rescale [0, 1] -> [0, 255].
    4. Convert RGB -> YCbCr color domain via dct.to_ycbcr().
    5. Subtract 128 level-shift.
    6. Unfold into 8x8 non-overlapping blocks.
    7. Compute block_dct() per 8x8 patch.
    8. Remove 10 specified low-frequency channels.

    Returns:
        Tensor of shape (B, 3 * 54, 112, 112) = (B, 162, 112, 112).
    """
    cfg = config or TransformConfig()
    assert x.shape[1] == 3, f"Expected 3 color channels, got {x.shape[1]}"

    # 1. Rescale to [0, 1]
    x = x * 0.5 + 0.5

    # 2. Upsample by ratio=8
    x = F.interpolate(x, scale_factor=cfg.ratio, mode="bilinear", align_corners=True)

    # 3-5. RGB -> YCbCr with 128 level-shift
    x = x * 255.0
    x = dct.to_ycbcr(x)
    x = x - 128.0

    # 6-7. Block DCT
    b, c, h, w = x.shape
    stride = cfg.stride
    size = cfg.block_size
    n_block = h // stride
    x = x.view(b * c, 1, h, w)
    x = F.unfold(x, kernel_size=(size, size), dilation=1, padding=0, stride=(stride, stride))
    x = x.transpose(1, 2)
    x = x.view(b, c, -1, size, size)
    x_freq = dct.block_dct(x)
    x_freq = x_freq.view(b, c, n_block, n_block, size * size).permute(0, 1, 4, 2, 3)

    # 8. Prune low-frequency channels
    # Preserve exact Python set subtraction ordering from research implementation:
    # channels = list(set([i for i in range(64)]) - set(chs_remove))
    channels = list(set(range(64)) - set(cfg.pruned_channels))
    x_freq = x_freq[:, :, channels, :, :]

    # Stack channels from each color plane: (B, 3 * 54, 112, 112)
    x_freq = x_freq.reshape(b, -1, n_block, n_block)
    return x_freq


def create_channel_subsets(
    x: torch.Tensor,
    config: TransformConfig | None = None,
) -> torch.Tensor:
    """
    Converts spatial images into 6 subsets of frequency channels via matrix S.

    Args:
        x: Normalized spatial tensor of shape (B, 3, 112, 112) in [-1, 1].

    Returns:
        Tensor of shape (B * 6, 27, 112, 112) organized subset-first:
        subset 0 for all batch samples, followed by subset 1, etc.
    """
    cfg = config or TransformConfig()
    x_freq = raw_bdct_transform(x, config=cfg)
    b, _c, h, w = x_freq.shape

    # c is 3 * 54 = 162
    num_kept = cfg.kept_frequency_channels
    x_freq = x_freq.reshape(b, 3, num_kept, h, w)

    selection = SUBSET_SELECTION_MATRIX.reshape(-1)
    x_freq = x_freq[:, :, selection]
    x_freq = torch.reshape(x_freq, (b, 3, cfg.num_subsets, cfg.channels_per_subset, h, w))
    x_freq = x_freq.permute(2, 0, 1, 3, 4, 5)

    # Shape: (B * 6, 27, 112, 112)
    x_freq = torch.reshape(x_freq, (b * cfg.num_subsets, 3 * cfg.channels_per_subset, h, w))
    return x_freq


def image_to_partial_frequency(
    image: np.ndarray | torch.Tensor,
    subset_index: int | None = None,
    perm_index: int | None = None,
    rng: np.random.Generator | int | None = None,
    config: TransformConfig | None = None,
) -> torch.Tensor:
    """
    Transforms an aligned RGB spatial face image into a 27-channel partial frequency tensor.

    PRIVACY GUARANTEE:
    Random frequency subset sampling ensures that each transmitted transaction reveals
    only 1 of 6 possible 9-channel frequency bands (16.7% of the high-frequency spectrum),
    while 100% of the low-frequency facial appearance (DC + structural skin features) is pruned.
    Even with infinite intercepted samples, the client never emits the low-frequency carrier
    required for facial reconstruction.

    Args:
        image: Aligned face (112, 112, 3) uint8 RGB or (3, 112, 112) float in [-1, 1].
        subset_index: Deterministic subset index [0..5]. If None, sampled via rng.
        perm_index: Deterministic permutation index [0..2]. If None, sampled via rng.
        rng: Controllable NumPy Generator or integer seed for tests. If None, uses secrets RNG.
        config: Transform configuration parameters.

    Returns:
        torch.Tensor of shape (27, 112, 112), dtype float32.
    """
    cfg = config or TransformConfig()
    x = _preprocess_spatial_input(image)  # (1, 3, 112, 112)

    # 1. Generate all 6 subsets: (6, 27, 112, 112)
    splits = create_channel_subsets(x, config=cfg)

    # 2. Select subset
    if subset_index is not None:
        if not (0 <= subset_index < cfg.num_subsets):
            raise ValueError(f"subset_index must be in [0, {cfg.num_subsets - 1}], got {subset_index}")
        chosen_subset = subset_index
    elif rng is not None:
        gen = np.random.default_rng(rng) if isinstance(rng, int) else rng
        chosen_subset = int(gen.integers(0, cfg.num_subsets))
    else:
        chosen_subset = secrets.randbelow(cfg.num_subsets)

    selected = splits[chosen_subset : chosen_subset + 1]  # (1, 27, 112, 112)

    # 3. Permute channels within the selected subset
    if perm_index is not None:
        if not (0 <= perm_index < len(CANDIDATE_PERMUTATIONS)):
            raise ValueError(f"perm_index must be in [0, {len(CANDIDATE_PERMUTATIONS) - 1}], got {perm_index}")
        chosen_perm = perm_index
    elif rng is not None:
        gen = np.random.default_rng(rng) if isinstance(rng, int) else rng
        chosen_perm = int(gen.integers(0, len(CANDIDATE_PERMUTATIONS)))
    else:
        chosen_perm = secrets.randbelow(len(CANDIDATE_PERMUTATIONS))

    perm = CANDIDATE_PERMUTATIONS[chosen_perm]

    # Permute 9 channels in each of the 3 color planes
    selected = selected.reshape(1, 3, cfg.channels_per_subset, 112, 112)
    selected[0] = selected[0, :, perm]
    output = selected.reshape(cfg.model_input_channels, 112, 112)

    return output.contiguous()


def batch_images_to_partial_frequency(
    images: Sequence[np.ndarray | torch.Tensor],
    subset_indices: Sequence[int] | None = None,
    perm_indices: Sequence[int] | None = None,
    rng: np.random.Generator | int | None = None,
    config: TransformConfig | None = None,
) -> torch.Tensor:
    """
    Batch transformation of aligned spatial face images into partial frequency tensors.

    Returns:
        torch.Tensor of shape (B, 27, 112, 112), dtype float32.
    """
    outputs = []
    for i, img in enumerate(images):
        s_idx = subset_indices[i] if subset_indices is not None else None
        p_idx = perm_indices[i] if perm_indices is not None else None
        out = image_to_partial_frequency(
            img,
            subset_index=s_idx,
            perm_index=p_idx,
            rng=rng,
            config=config,
        )
        outputs.append(out)

    return torch.stack(outputs, dim=0)
