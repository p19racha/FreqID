# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_embedder.py: Unit tests for Embedder inference, backends, and normalization.
"""

import os

import numpy as np
import pytest

from freqid_core.embedder import Embedder
from freqid_core.errors import ShapeMismatchError
from freqid_core.payload import PartialFacePayload

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CKPT_PATH = os.path.join(
    REPO_ROOT, "research", "outputs", "checkpoints", "partialface_ir_18_epoch5.pth"
)
ONNX_PATH = os.path.join(REPO_ROOT, "research", "outputs", "checkpoints", "partialface_ir_18.onnx")


def test_embedder_load_torch():
    embedder = Embedder.from_checkpoint(CKPT_PATH, backend="torch", device="cpu")
    info = embedder.model_info()

    assert info.backend == "torch"
    assert info.embedding_dim == 512
    assert info.input_shape == (27, 112, 112)
    assert len(info.checkpoint_hash) == 64


def test_embedder_load_onnx():
    if not os.path.exists(ONNX_PATH):
        pytest.skip("ONNX checkpoint not generated yet")

    embedder = Embedder.from_checkpoint(ONNX_PATH, backend="onnx", device="cpu")
    info = embedder.model_info()

    assert info.backend == "onnx"
    assert info.embedding_dim == 512


def test_embedder_l2_normalization():
    embedder = Embedder.from_checkpoint(CKPT_PATH, backend="torch", device="cpu")
    data = np.random.randn(27, 112, 112).astype(np.float32)

    emb = embedder.embed(data)
    assert emb.shape == (512,)
    norm = np.linalg.norm(emb)
    assert np.isclose(norm, 1.0, atol=1e-5)


def test_embedder_batch_consistency():
    embedder = Embedder.from_checkpoint(CKPT_PATH, backend="torch", device="cpu")
    img1 = np.random.randn(27, 112, 112).astype(np.float32)
    img2 = np.random.randn(27, 112, 112).astype(np.float32)

    # Embed individually
    emb1 = embedder.embed(img1)
    emb2 = embedder.embed(img2)

    # Embed as batch
    batch_emb = embedder.embed(np.stack([img1, img2]))

    np.testing.assert_allclose(batch_emb[0], emb1, atol=1e-5)
    np.testing.assert_allclose(batch_emb[1], emb2, atol=1e-5)


def test_embedder_rejects_3channel_raw_image():
    embedder = Embedder.from_checkpoint(CKPT_PATH, backend="torch", device="cpu")
    raw_img = np.random.randn(3, 112, 112).astype(np.float32)

    with pytest.raises(ShapeMismatchError, match="partial frequency shape"):
        embedder.embed(raw_img)


def test_embedder_from_payload():
    embedder = Embedder.from_checkpoint(CKPT_PATH, backend="torch", device="cpu")
    data = np.random.randn(27, 112, 112).astype(np.float32)
    payload = PartialFacePayload(data)

    emb = embedder.embed(payload)
    assert emb.shape == (512,)
    assert np.isclose(np.linalg.norm(emb), 1.0, atol=1e-5)
