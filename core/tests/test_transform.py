# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_transform.py: Unit tests for client-side transform, channel pruning, and sampling.
"""

import numpy as np
import pytest
import torch

from freqid_core.errors import ShapeMismatchError
from freqid_core.transform import (
    batch_images_to_partial_frequency,
    image_to_partial_frequency,
)


def test_transform_shape_and_dtype():
    # Synthetic RGB face: (112, 112, 3) uint8
    img = np.random.randint(0, 256, (112, 112, 3), dtype=np.uint8)
    out = image_to_partial_frequency(img, subset_index=0, perm_index=0)

    assert isinstance(out, torch.Tensor)
    assert out.shape == (27, 112, 112)
    assert out.dtype == torch.float32


def test_transform_determinism():
    img = np.random.randint(0, 256, (112, 112, 3), dtype=np.uint8)

    # Same subset and perm
    out1 = image_to_partial_frequency(img, subset_index=2, perm_index=1)
    out2 = image_to_partial_frequency(img, subset_index=2, perm_index=1)
    assert torch.equal(out1, out2)

    # Same seed
    out_seed1 = image_to_partial_frequency(img, rng=42)
    out_seed2 = image_to_partial_frequency(img, rng=42)
    assert torch.equal(out_seed1, out_seed2)


def test_transform_randomness():
    img = np.random.randint(0, 256, (112, 112, 3), dtype=np.uint8)
    out1 = image_to_partial_frequency(img, rng=1)
    out2 = image_to_partial_frequency(img, rng=9999)
    # Different seeds should sample different subsets / permutations
    assert not torch.equal(out1, out2)


def test_batch_transform():
    imgs = [np.random.randint(0, 256, (112, 112, 3), dtype=np.uint8) for _ in range(4)]
    batch_out = batch_images_to_partial_frequency(imgs, rng=123)

    assert isinstance(batch_out, torch.Tensor)
    assert batch_out.shape == (4, 27, 112, 112)


def test_invalid_input_shapes():
    # Wrong resolution (64, 64, 3)
    bad_img = np.zeros((64, 64, 3), dtype=np.uint8)
    with pytest.raises(ShapeMismatchError):
        image_to_partial_frequency(bad_img)

    # Wrong channels (112, 112, 1)
    bad_img2 = np.zeros((112, 112, 1), dtype=np.uint8)
    with pytest.raises(ShapeMismatchError):
        image_to_partial_frequency(bad_img2)
