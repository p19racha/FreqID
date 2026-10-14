# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_detect_and_align.py: Unit tests for face detection, landmark extraction, and 5-point alignment.
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from freqid_client.align import (
    REFERENCE_5_POINTS,
    align_face,
    estimate_similarity_transform,
)
from freqid_client.detect import YuNetFaceDetector

REPO_ROOT = Path(__file__).parent.parent.parent
MODEL_PATH = (
    Path(__file__).parent.parent
    / "src"
    / "freqid_client"
    / "models"
    / "face_detection_yunet_2023mar.onnx"
)
SAMPLE_FACE = REPO_ROOT / "data" / "train_subset" / "images" / "id_0000" / "img_00.png"


def test_similarity_transform_known_points():
    # Transform identical points -> should yield identity matrix
    m = estimate_similarity_transform(REFERENCE_5_POINTS, REFERENCE_5_POINTS)
    np.testing.assert_allclose(m[0:2, 0:2], np.eye(2), atol=1e-5)
    np.testing.assert_allclose(m[0:2, 2], np.zeros(2), atol=1e-5)


def test_align_face_shape():
    raw = np.random.randint(0, 256, (320, 320, 3), dtype=np.uint8)
    # Synthetic landmarks
    lmks = np.array(
        [
            [140.0, 140.0],
            [180.0, 140.0],
            [160.0, 160.0],
            [145.0, 180.0],
            [175.0, 180.0],
        ],
        dtype=np.float32,
    )

    crop = align_face(raw, lmks, crop_size=(112, 112))
    assert crop.shape == (112, 112, 3)
    assert crop.dtype == np.uint8


def test_yunet_detection_on_canvas():
    if not MODEL_PATH.is_file() or not SAMPLE_FACE.is_file():
        pytest.skip("Required model or test image not found.")

    detector = YuNetFaceDetector(model_path=MODEL_PATH, score_threshold=0.3)
    face_img = cv2.imread(str(SAMPLE_FACE))

    # Place in 320x320 canvas to simulate camera frame
    canvas = np.full((320, 320, 3), 128, dtype=np.uint8)
    canvas[100:212, 100:212] = face_img

    detections = detector.detect(canvas)
    assert len(detections) >= 1

    d = detections[0]
    assert d.score > 0.5
    assert d.landmarks.shape == (5, 2)
    # Coordinates should fall roughly within canvas placement [100..212]
    assert 100 <= d.landmarks[:, 0].mean() <= 212
    assert 100 <= d.landmarks[:, 1].mean() <= 212
