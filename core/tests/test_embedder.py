# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_embedder.py: Unit tests for Embedder inference, backends, and normalization.
"""

import numpy as np
import pytest
import torch

from freqid_core.embedder import Embedder
from freqid_core.errors import ShapeMismatchError
from freqid_core.export_onnx import export_to_onnx
from freqid_core.model import IR_18_Partial
from freqid_core.payload import PartialFacePayload


@pytest.fixture(scope="module")
def torch_ckpt_path(tmp_path_factory: pytest.TempPathFactory) -> str:
    ckpt_dir = tmp_path_factory.mktemp("checkpoints")
    ckpt_path = ckpt_dir / "partialface_ir_18_epoch5.pth"
    model = IR_18_Partial(input_channel=27, embedding_dim=512)
    torch.save({"backbone": model.state_dict()}, ckpt_path)
    return str(ckpt_path)


@pytest.fixture(scope="module")
def onnx_ckpt_path(tmp_path_factory: pytest.TempPathFactory) -> str:
    ckpt_dir = tmp_path_factory.mktemp("checkpoints")
    onnx_path = ckpt_dir / "partialface_ir_18.onnx"
    model = IR_18_Partial(input_channel=27, embedding_dim=512)
    return export_to_onnx(model, str(onnx_path), opset_version=14, dynamic_batch=True)


def test_embedder_load_torch(torch_ckpt_path: str):
    embedder = Embedder.from_checkpoint(torch_ckpt_path, backend="torch", device="cpu")
    info = embedder.model_info()

    assert info.backend == "torch"
    assert info.embedding_dim == 512
    assert info.input_shape == (27, 112, 112)
    assert len(info.checkpoint_hash) == 64


def test_embedder_load_onnx(onnx_ckpt_path: str):
    embedder = Embedder.from_checkpoint(onnx_ckpt_path, backend="onnx", device="cpu")
    info = embedder.model_info()

    assert info.backend == "onnx"
    assert info.embedding_dim == 512


def test_embedder_l2_normalization(torch_ckpt_path: str):
    embedder = Embedder.from_checkpoint(torch_ckpt_path, backend="torch", device="cpu")
    data = np.random.randn(27, 112, 112).astype(np.float32)

    emb = embedder.embed(data)
    assert emb.shape == (512,)
    norm = np.linalg.norm(emb)
    assert np.isclose(norm, 1.0, atol=1e-5)


def test_embedder_batch_consistency(torch_ckpt_path: str):
    embedder = Embedder.from_checkpoint(torch_ckpt_path, backend="torch", device="cpu")
    img1 = np.random.randn(27, 112, 112).astype(np.float32)
    img2 = np.random.randn(27, 112, 112).astype(np.float32)

    # Embed individually
    emb1 = embedder.embed(img1)
    emb2 = embedder.embed(img2)

    # Embed as batch
    batch_emb = embedder.embed(np.stack([img1, img2]))

    np.testing.assert_allclose(batch_emb[0], emb1, atol=1e-5)
    np.testing.assert_allclose(batch_emb[1], emb2, atol=1e-5)


def test_embedder_rejects_3channel_raw_image(torch_ckpt_path: str):
    embedder = Embedder.from_checkpoint(torch_ckpt_path, backend="torch", device="cpu")
    raw_img = np.random.randn(3, 112, 112).astype(np.float32)

    with pytest.raises(ShapeMismatchError, match="partial frequency shape"):
        embedder.embed(raw_img)


def test_embedder_from_payload(torch_ckpt_path: str):
    embedder = Embedder.from_checkpoint(torch_ckpt_path, backend="torch", device="cpu")
    data = np.random.randn(27, 112, 112).astype(np.float32)
    payload = PartialFacePayload(data)

    emb = embedder.embed(payload)
    assert emb.shape == (512,)
    assert np.isclose(np.linalg.norm(emb), 1.0, atol=1e-5)
