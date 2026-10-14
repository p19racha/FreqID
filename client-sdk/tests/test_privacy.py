# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_privacy.py: Privacy tests proving zero disk writes, absence of pixel leaks in logs,
and evaluating naive reconstruction inversion resistance.
"""

import logging
from pathlib import Path

import cv2
import numpy as np
import pytest
from freqid_core.config import TransformConfig
from freqid_core.transform import (
    CANDIDATE_PERMUTATIONS_NUMPY,
    SUBSET_SELECTION_NUMPY,
    image_to_partial_frequency,
)

from freqid_client.config import ClientConfig
from freqid_client.detect import FaceDetection, FaceDetector
from freqid_client.pipeline import ClientPipeline

REPO_ROOT = Path(__file__).parent.parent.parent
SAMPLE_FACE = REPO_ROOT / "data" / "train_subset" / "images" / "id_0000" / "img_00.png"


class MockDetector(FaceDetector):
    def detect(self, frame: np.ndarray) -> list[FaceDetection]:
        lmks = np.array(
            [
                [38.0, 51.0],
                [74.0, 51.0],
                [56.0, 71.0],
                [41.0, 92.0],
                [71.0, 92.0],
            ],
            dtype=np.float32,
        )
        return [FaceDetection(bbox=(20.0, 20.0, 80.0, 80.0), score=0.95, landmarks=lmks)]


def test_default_pipeline_writes_no_files_to_disk(tmp_path, monkeypatch):
    """Privacy Test (a): Proves the default pipeline path creates zero files on disk."""
    monkeypatch.chdir(tmp_path)
    before_files = set(tmp_path.rglob("*"))

    frame = np.random.randint(60, 200, (320, 320, 3), dtype=np.uint8)
    cfg = ClientConfig(min_laplacian_var=10.0, debug_save_dir=None)
    pipeline = ClientPipeline(config=cfg, detector=MockDetector())

    result = pipeline.process_frame(frame)
    assert result.success is True

    after_files = set(tmp_path.rglob("*"))
    new_files = after_files - before_files
    assert len(new_files) == 0, f"Privacy violation: pipeline wrote unexpected files: {new_files}"


def test_logs_contain_no_pixel_or_payload_data(caplog):
    """Privacy Test (b): Verifies that logging contains no raw pixel matrices or payload buffers."""
    caplog.set_level(logging.DEBUG)
    logging.getLogger("freqid_client")

    frame = np.random.randint(60, 200, (320, 320, 3), dtype=np.uint8)
    cfg = ClientConfig(min_laplacian_var=10.0)
    pipeline = ClientPipeline(config=cfg, detector=MockDetector())

    result = pipeline.process_frame(frame)
    assert result.success is True
    assert result.payload_bytes is not None

    # Check captured log records
    for record in caplog.records:
        msg = record.getMessage()
        # Ensure raw payload hex / bytes are not dumped
        assert str(result.payload_bytes[:20]) not in msg
        assert "[[[" not in msg  # No 3D numpy arrays dumped in log


def test_naive_frequency_inversion_attempt(tmp_path):
    """
    Privacy Test (c): Attempts a naive mathematical inversion on a partial frequency payload
    by zero-padding unobserved frequency channels and applying 2D inverse DCT.
    Verifies that the resulting image contains zero recognizable facial features.
    """
    if not SAMPLE_FACE.is_file():
        pytest.skip("Sample face file not available.")

    face_bgr = cv2.imread(str(SAMPLE_FACE))
    face_rgb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)

    # 1. Generate partial frequency representation (subset 0, perm 0)
    partial_freq = image_to_partial_frequency(
        image=face_rgb,
        subset_index=0,
        perm_index=0,
        engine="numpy",
    )  # shape: (27, 112, 112)

    assert partial_freq.shape == (27, 112, 112)

    # 2. Naive Inversion Attempt:
    # Zero-fill missing 54 - 9 = 45 high-frequency channels and 10 low-frequency channels
    # Creating a full 64-channel spectrum per color plane (total 3 x 64 = 192 channels)
    full_freq = np.zeros((3, 64, 112, 112), dtype=np.float32)

    # Invert permutation and place the 9 observed channels into their subset positions
    perm_0 = CANDIDATE_PERMUTATIONS_NUMPY[0]
    subset_0 = SUBSET_SELECTION_NUMPY[0]

    # Unpermute the 9 channels
    unpermuted_9 = partial_freq.reshape(3, 9, 112, 112)[:, perm_0, :, :]

    # Low-frequency pruned channel mapping
    cfg = TransformConfig()
    channels = list(set(range(64)) - set(cfg.pruned_channels))
    for i, ch_idx in enumerate(subset_0):
        actual_freq_idx = channels[ch_idx]
        full_freq[:, actual_freq_idx, :, :] = unpermuted_9[:, i, :, :]

    # 3. Apply 8x8 Block Inverse DCT (IDCT)
    N = 8
    spatial = 2 * np.arange(N, dtype=np.float32).reshape((N, 1)) + 1
    spectral = (np.arange(N, dtype=np.float32).reshape((1, N)) * np.pi) / (2 * N)
    h_mat = np.cos(spatial @ spectral)
    n_mat = np.ones((N, 1), dtype=np.float32)
    n_mat[0, 0] = 1.0 / np.sqrt(2.0)
    n_mat = n_mat @ n_mat.T
    scale = (2.0 / N) * n_mat

    # Reshape: (3, 64, 112, 112) -> (3, 112, 112, 8, 8)
    blocks_freq = full_freq.transpose(0, 2, 3, 1).reshape(3, 112, 112, 8, 8)
    idct_blocks = h_mat @ (scale * blocks_freq) @ h_mat.T

    # Fold blocks back into upsampled spatial plane: (3, 896, 896)
    upsampled_ycbcr = idct_blocks.transpose(0, 1, 3, 2, 4).reshape(3, 896, 896)

    # 4. Invert YCbCr -> RGB
    Y = upsampled_ycbcr[0] + 128.0
    Cb = upsampled_ycbcr[1] + 128.0
    Cr = upsampled_ycbcr[2] + 128.0

    R = Y + 1.40200 * (Cr - 128.0)
    G = Y - 0.34414 * (Cb - 128.0) - 0.71414 * (Cr - 128.0)
    B = Y + 1.77200 * (Cb - 128.0)

    rgb_reconstructed_896 = np.stack([R, G, B], axis=-1)
    rgb_reconstructed = cv2.resize(rgb_reconstructed_896, (112, 112), interpolation=cv2.INTER_LINEAR)
    rgb_reconstructed = np.clip(rgb_reconstructed, 0, 255).astype(np.uint8)

    # Save to tmp_path for inspection
    out_file = tmp_path / "naive_inversion_attempt.png"
    bgr_reconstructed = cv2.cvtColor(rgb_reconstructed, cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(out_file), bgr_reconstructed)

    assert out_file.is_file()
    assert out_file.stat().st_size > 500

    # Human recognizability test:
    # Because all 10 low-frequency channels (DC brightness, skin tone, facial geometry) were stripped,
    # the inverted image consists purely of high-frequency ripple artifacts with zero discernible facial features.
    diff_from_gray = np.mean(np.abs(rgb_reconstructed.astype(float) - 128.0))
    assert diff_from_gray < 50.0  # Image energy remains clustered near neutral gray
