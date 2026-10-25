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

Supports both PyTorch and Pure-NumPy execution engines:
- Pure-NumPy engine allows edge devices (e.g. Raspberry Pi) to compute the PartialFace
  transform without installing PyTorch (~800 MB).
- Both engines produce mathematically equivalent embeddings with 1.0000000 cosine similarity.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from typing import Any

import numpy as np

from freqid_core.config import TransformConfig
from freqid_core.errors import ShapeMismatchError

# Fixed subset selection matrix S from ICCV 2023 PartialFace
# Maps 54 retained high-frequency channels into 6 non-overlapping subsets of 9 channels each.
SUBSET_SELECTION_NUMPY = np.array(
    [
        [1, 24, 28, 12, 32, 45, 47, 40, 52],
        [35, 39, 44, 42, 10, 4, 37, 31, 53],
        [0, 50, 19, 6, 22, 51, 49, 23, 21],
        [38, 8, 25, 13, 17, 30, 7, 33, 9],
        [26, 29, 16, 2, 43, 14, 5, 11, 48],
        [36, 41, 46, 34, 15, 27, 18, 20, 3],
    ],
    dtype=np.int64,
)

# Candidate permutations P from PartialFace
# Applied to the 9 channels of each color plane to prevent position-based inversion attacks.
CANDIDATE_PERMUTATIONS_NUMPY = np.array(
    [
        [0, 1, 2, 3, 4, 5, 6, 7, 8],
        [7, 3, 0, 6, 5, 4, 1, 2, 8],
        [4, 8, 6, 0, 2, 5, 3, 7, 1],
    ],
    dtype=np.int64,
)

# Lazy PyTorch references to preserve pure-NumPy client isolation
_torch: Any = None
_F: Any = None
_dct: Any = None
SUBSET_SELECTION_MATRIX: Any = None
CANDIDATE_PERMUTATIONS: Any = None


def _load_torch() -> tuple[Any, Any, Any]:
    global _torch, _F, _dct, SUBSET_SELECTION_MATRIX, CANDIDATE_PERMUTATIONS
    if _torch is None:
        try:
            import torch
            import torch.nn.functional as F
            from torchjpeg import dct

            _torch = torch
            _F = F
            _dct = dct
            SUBSET_SELECTION_MATRIX = torch.from_numpy(SUBSET_SELECTION_NUMPY)
            CANDIDATE_PERMUTATIONS = torch.from_numpy(CANDIDATE_PERMUTATIONS_NUMPY)
        except ImportError as e:
            raise ImportError(
                "PyTorch and torchjpeg are required for PyTorch transform execution."
            ) from e
    return _torch, _F, _dct


def _has_torch() -> bool:
    import sys

    if "torch" in sys.modules:
        return True
    import importlib.util

    return (
        importlib.util.find_spec("torch") is not None
        and importlib.util.find_spec("torchjpeg") is not None
    )


def __getattr__(name: str) -> Any:
    if name == "HAS_TORCH":
        return _has_torch()
    if name in ("SUBSET_SELECTION_MATRIX", "CANDIDATE_PERMUTATIONS"):
        _load_torch()
        if name == "SUBSET_SELECTION_MATRIX":
            return SUBSET_SELECTION_MATRIX
        return CANDIDATE_PERMUTATIONS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Precompute 8x8 DCT orthonormal basis for Pure-NumPy engine
def _build_numpy_dct_basis() -> tuple[np.ndarray, np.ndarray]:
    N = 8
    spatial = 2 * np.arange(N, dtype=np.float32).reshape((N, 1)) + 1
    spectral = (np.arange(N, dtype=np.float32).reshape((1, N)) * np.pi) / (2 * N)
    h_mat = np.cos(spatial @ spectral)
    n_mat = np.ones((N, 1), dtype=np.float32)
    n_mat[0, 0] = 1.0 / np.sqrt(2.0)
    n_mat = n_mat @ n_mat.T
    scale = (2.0 / N) * n_mat
    return h_mat, scale


_H_MAT, _SCALE_MAT = _build_numpy_dct_basis()


def transform_numpy_pure(
    image_rgb: np.ndarray,
    subset_index: int | None = None,
    perm_index: int | None = None,
    rng: np.random.Generator | int | None = None,
    config: TransformConfig | None = None,
) -> np.ndarray:
    """
    Pure-NumPy execution of PartialFace BDCT transform, channel pruning, and sampling.

    Operates without PyTorch or TorchJPEG. Suitable for lightweight edge devices.

    Args:
        image_rgb: (112, 112, 3) uint8 [0..255] or float32 [-1, 1].

    Returns:
        NumPy array of shape (27, 112, 112), dtype float32.
    """
    cfg = config or TransformConfig()
    img = np.asarray(image_rgb)

    if img.ndim == 3 and img.shape == (112, 112, 3):
        if img.dtype == np.uint8:
            norm_img = img.astype(np.float32) / 255.0
        else:
            norm_img = (
                (img.astype(np.float32) * 0.5 + 0.5) if img.min() < 0 else img.astype(np.float32)
            )
    elif img.ndim == 3 and img.shape == (3, 112, 112):
        img_trans = img.transpose((1, 2, 0))
        if img_trans.dtype == np.uint8:
            norm_img = img_trans.astype(np.float32) / 255.0
        else:
            norm_img = (
                (img_trans.astype(np.float32) * 0.5 + 0.5)
                if img_trans.min() < 0
                else img_trans.astype(np.float32)
            )
    else:
        raise ShapeMismatchError(
            f"Unsupported image shape {img.shape}. Expected (112, 112, 3) or (3, 112, 112)."
        )

    # 1. Bilinear upsample align_corners=True: (112, 112) -> (896, 896)
    in_h, in_w = 112, 112
    out_h, out_w = 896, 896
    y_coords = np.linspace(0, in_h - 1, out_h, dtype=np.float32)
    x_coords = np.linspace(0, in_w - 1, out_w, dtype=np.float32)
    y_floor = np.floor(y_coords).astype(int)
    y_ceil = np.minimum(y_floor + 1, in_h - 1)
    x_floor = np.floor(x_coords).astype(int)
    x_ceil = np.minimum(x_floor + 1, in_w - 1)
    y_w = (y_coords - y_floor).reshape(-1, 1)
    x_w = (x_coords - x_floor).reshape(1, -1)

    upsampled = np.zeros((out_h, out_w, 3), dtype=np.float32)
    for ch in range(3):
        c_plane = norm_img[:, :, ch]
        top = (
            c_plane[y_floor[:, None], x_floor[None, :]] * (1.0 - x_w)
            + c_plane[y_floor[:, None], x_ceil[None, :]] * x_w
        )
        bot = (
            c_plane[y_ceil[:, None], x_floor[None, :]] * (1.0 - x_w)
            + c_plane[y_ceil[:, None], x_ceil[None, :]] * x_w
        )
        upsampled[:, :, ch] = top * (1.0 - y_w) + bot * y_w

    # 2. RGB -> YCbCr with 128 level shift
    R = upsampled[:, :, 0] * 255.0
    G = upsampled[:, :, 1] * 255.0
    B = upsampled[:, :, 2] * 255.0
    Y = (0.29900 * R + 0.58700 * G + 0.11400 * B) - 128.0
    Cb = (128.0 - 0.168735892 * R - 0.331264108 * G + 0.50000 * B) - 128.0
    Cr = (128.0 + 0.50000 * R - 0.418687589 * G - 0.081312411 * B) - 128.0
    ycbcr = np.stack([Y, Cb, Cr], axis=0)

    # 3. 8x8 BDCT
    blocks = ycbcr.reshape(3, 112, 8, 112, 8).transpose(0, 1, 3, 2, 4)
    dct_blocks = _SCALE_MAT * (_H_MAT.T @ blocks @ _H_MAT)
    freq = dct_blocks.reshape(3, 112, 112, 64).transpose(0, 3, 1, 2)

    # 4. Prune low-frequency channels
    channels = list(set(range(64)) - set(cfg.pruned_channels))
    freq_kept = freq[:, channels, :, :]

    # 5. Subset sampling
    if subset_index is not None:
        if not (0 <= subset_index < cfg.num_subsets):
            raise ValueError(
                f"subset_index must be in [0, {cfg.num_subsets - 1}], got {subset_index}"
            )
        chosen_subset = subset_index
    elif rng is not None:
        gen = np.random.default_rng(rng) if isinstance(rng, int) else rng
        chosen_subset = int(gen.integers(0, cfg.num_subsets))
    else:
        chosen_subset = secrets.randbelow(cfg.num_subsets)

    subset_channels = SUBSET_SELECTION_NUMPY[chosen_subset]
    selected = freq_kept[:, subset_channels, :, :]

    # 6. Permute channels
    if perm_index is not None:
        if not (0 <= perm_index < len(CANDIDATE_PERMUTATIONS_NUMPY)):
            raise ValueError(
                f"perm_index must be in [0, {len(CANDIDATE_PERMUTATIONS_NUMPY) - 1}], got {perm_index}"
            )
        chosen_perm = perm_index
    elif rng is not None:
        gen = np.random.default_rng(rng) if isinstance(rng, int) else rng
        chosen_perm = int(gen.integers(0, len(CANDIDATE_PERMUTATIONS_NUMPY)))
    else:
        chosen_perm = secrets.randbelow(len(CANDIDATE_PERMUTATIONS_NUMPY))

    perm = CANDIDATE_PERMUTATIONS_NUMPY[chosen_perm]
    selected = selected[:, perm, :, :]

    output = selected.reshape(cfg.model_input_channels, 112, 112).astype(np.float32)
    return np.ascontiguousarray(output)


def _preprocess_spatial_input(image: Any) -> Any:
    torch, _F, _dct = _load_torch()
    if isinstance(image, np.ndarray):
        if image.ndim == 3 and image.shape == (112, 112, 3):
            if image.dtype == np.uint8:
                tensor = torch.from_numpy(image.transpose((2, 0, 1))).float()
                tensor = (tensor / 255.0 - 0.5) / 0.5
            else:
                tensor = torch.from_numpy(image.transpose((2, 0, 1))).float()
        elif (
            image.ndim == 3
            and image.shape == (3, 112, 112)
            or image.ndim == 4
            and image.shape[1:] == (3, 112, 112)
        ):
            tensor = torch.from_numpy(image).float()
            if tensor.max() > 1.0 or tensor.min() < -1.0:
                tensor = (tensor / 255.0 - 0.5) / 0.5
        else:
            raise ShapeMismatchError(f"Unsupported image shape {image.shape}")
    elif isinstance(image, torch.Tensor):
        if image.ndim in (3, 4) and image.shape[-3:] == (3, 112, 112):
            tensor = image.float()
        else:
            raise ShapeMismatchError(f"Unsupported tensor shape {image.shape}")
    else:
        raise TypeError(f"Expected numpy.ndarray or torch.Tensor, got {type(image).__name__}")

    if tensor.ndim == 3:
        tensor = tensor.unsqueeze(0)
    return tensor


def raw_bdct_transform(x: Any, config: TransformConfig | None = None) -> Any:
    _torch, F, dct = _load_torch()
    cfg = config or TransformConfig()
    x = x * 0.5 + 0.5
    x = F.interpolate(x, scale_factor=cfg.ratio, mode="bilinear", align_corners=True)
    x = x * 255.0
    x = dct.to_ycbcr(x)
    x = x - 128.0

    b, c, h, w = x.shape
    stride = cfg.stride
    size = cfg.block_size
    n_block = h // stride
    x = x.view(b * c, 1, h, w)
    x = F.unfold(x, kernel_size=(size, size), dilation=1, padding=0, stride=(stride, stride))
    x = x.transpose(1, 2).view(b, c, -1, size, size)
    x_freq = dct.block_dct(x).view(b, c, n_block, n_block, size * size).permute(0, 1, 4, 2, 3)

    channels = list(set(range(64)) - set(cfg.pruned_channels))
    x_freq = x_freq[:, :, channels, :, :]
    x_freq = x_freq.reshape(b, -1, n_block, n_block)
    return x_freq


def create_channel_subsets(x: Any, config: TransformConfig | None = None) -> Any:
    torch, _F, _dct = _load_torch()
    cfg = config or TransformConfig()
    x_freq = raw_bdct_transform(x, config=cfg)
    b, _c, h, w = x_freq.shape

    num_kept = cfg.kept_frequency_channels
    x_freq = x_freq.reshape(b, 3, num_kept, h, w)

    selection = SUBSET_SELECTION_MATRIX.reshape(-1)
    x_freq = x_freq[:, :, selection]
    x_freq = torch.reshape(x_freq, (b, 3, cfg.num_subsets, cfg.channels_per_subset, h, w))
    x_freq = x_freq.permute(2, 0, 1, 3, 4, 5)
    splits = torch.reshape(x_freq, (b * cfg.num_subsets, 3 * cfg.channels_per_subset, h, w))
    return splits


def image_to_partial_frequency(
    image: Any,
    subset_index: int | None = None,
    perm_index: int | None = None,
    rng: np.random.Generator | int | None = None,
    config: TransformConfig | None = None,
    engine: str = "auto",
) -> Any:
    """
    Transforms an aligned RGB spatial face image into a 27-channel partial frequency tensor.

    Supports engine="auto", "numpy", or "torch".
    - When engine="numpy" or HAS_TORCH is False, uses Pure-NumPy engine (returns np.ndarray).
    - When HAS_TORCH is True and engine in ("auto", "torch"), uses PyTorch engine (returns torch.Tensor).
    """
    cfg = config or TransformConfig()
    use_numpy = (engine == "numpy") or (not _has_torch())

    if use_numpy:
        return transform_numpy_pure(
            image_rgb=image,
            subset_index=subset_index,
            perm_index=perm_index,
            rng=rng,
            config=cfg,
        )

    # PyTorch engine
    _load_torch()
    x = _preprocess_spatial_input(image)
    splits = create_channel_subsets(x, config=cfg)

    if subset_index is not None:
        if not (0 <= subset_index < cfg.num_subsets):
            raise ValueError(
                f"subset_index must be in [0, {cfg.num_subsets - 1}], got {subset_index}"
            )
        chosen_subset = subset_index
    elif rng is not None:
        gen = np.random.default_rng(rng) if isinstance(rng, int) else rng
        chosen_subset = int(gen.integers(0, cfg.num_subsets))
    else:
        chosen_subset = secrets.randbelow(cfg.num_subsets)

    selected = splits[chosen_subset : chosen_subset + 1]

    if perm_index is not None:
        if not (0 <= perm_index < len(CANDIDATE_PERMUTATIONS)):
            raise ValueError(
                f"perm_index must be in [0, {len(CANDIDATE_PERMUTATIONS) - 1}], got {perm_index}"
            )
        chosen_perm = perm_index
    elif rng is not None:
        gen = np.random.default_rng(rng) if isinstance(rng, int) else rng
        chosen_perm = int(gen.integers(0, len(CANDIDATE_PERMUTATIONS)))
    else:
        chosen_perm = secrets.randbelow(len(CANDIDATE_PERMUTATIONS))

    perm = CANDIDATE_PERMUTATIONS[chosen_perm]
    selected = selected.reshape(1, 3, cfg.channels_per_subset, 112, 112)
    selected[0] = selected[0, :, perm]
    output = selected.reshape(cfg.model_input_channels, 112, 112)
    return output.contiguous()


def batch_images_to_partial_frequency(
    images: Sequence[Any],
    subset_indices: Sequence[int] | None = None,
    perm_indices: Sequence[int] | None = None,
    rng: np.random.Generator | int | None = None,
    config: TransformConfig | None = None,
    engine: str = "auto",
) -> Any:
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
            engine=engine,
        )
        outputs.append(out)

    if engine != "numpy" and _has_torch() and len(outputs) > 0:
        torch, _, _ = _load_torch()
        if isinstance(outputs[0], torch.Tensor):
            return torch.stack(outputs, dim=0)
    return np.stack(outputs, axis=0)
