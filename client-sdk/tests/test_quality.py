# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_quality.py: Unit tests for QualityGate evaluating blur, brightness, face size, and pose.
"""

import numpy as np
import pytest

from freqid_client.detect import FaceDetection
from freqid_client.quality import QualityGate


@pytest.fixture
def base_detection():
    # Canonical frontal face landmarks in 112x112 space
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
    return FaceDetection(bbox=(20.0, 20.0, 80.0, 80.0), score=0.9, landmarks=lmks)


def test_quality_gate_no_face():
    qg = QualityGate()
    frame = np.full((320, 320, 3), 128, dtype=np.uint8)
    report = qg.evaluate(frame, detections=[])

    assert report.passed is False
    assert report.failure_code == "NO_FACE_DETECTED"


def test_quality_gate_multiple_faces(base_detection):
    qg = QualityGate(allow_multiple_faces=False)
    frame = np.full((320, 320, 3), 128, dtype=np.uint8)
    report = qg.evaluate(frame, detections=[base_detection, base_detection])

    assert report.passed is False
    assert report.failure_code == "MULTIPLE_FACES_DETECTED"


def test_quality_gate_face_too_small():
    qg = QualityGate(min_face_size=60)
    frame = np.full((320, 320, 3), 128, dtype=np.uint8)
    tiny_det = FaceDetection(
        bbox=(50.0, 50.0, 30.0, 30.0),
        score=0.9,
        landmarks=np.zeros((5, 2), dtype=np.float32),
    )
    report = qg.evaluate(frame, detections=[tiny_det])

    assert report.passed is False
    assert report.failure_code == "FACE_TOO_SMALL"


def test_quality_gate_image_too_dark(base_detection):
    qg = QualityGate(min_brightness=40.0)
    # Uniform dark frame (brightness ~10)
    dark_crop = np.full((112, 112, 3), 10, dtype=np.uint8)
    report = qg.evaluate(frame=dark_crop, detections=[base_detection], aligned_crop=dark_crop)

    assert report.passed is False
    assert report.failure_code == "IMAGE_TOO_DARK"


def test_quality_gate_image_too_bright(base_detection):
    qg = QualityGate(max_brightness=220.0)
    bright_crop = np.full((112, 112, 3), 245, dtype=np.uint8)
    report = qg.evaluate(frame=bright_crop, detections=[base_detection], aligned_crop=bright_crop)

    assert report.passed is False
    assert report.failure_code == "IMAGE_TOO_BRIGHT"


def test_quality_gate_image_too_blurry(base_detection):
    qg = QualityGate(min_laplacian_var=80.0)
    # Uniform gray image has 0 variance of Laplacian
    flat_crop = np.full((112, 112, 3), 128, dtype=np.uint8)
    report = qg.evaluate(frame=flat_crop, detections=[base_detection], aligned_crop=flat_crop)

    assert report.passed is False
    assert report.failure_code == "IMAGE_TOO_BLURRY"


def test_quality_gate_pose_extreme():
    qg = QualityGate(max_yaw_angle=15.0)
    frame = np.full((320, 320, 3), 128, dtype=np.uint8)
    # Nose shifted extremely to the right
    turned_lmks = np.array(
        [
            [30.0, 51.0],
            [70.0, 51.0],
            [90.0, 71.0],  # Nose way past right eye
            [40.0, 92.0],
            [70.0, 92.0],
        ],
        dtype=np.float32,
    )
    turned_det = FaceDetection(bbox=(20.0, 20.0, 80.0, 80.0), score=0.9, landmarks=turned_lmks)
    report = qg.evaluate(frame, detections=[turned_det])

    assert report.passed is False
    assert report.failure_code == "POSE_TOO_EXTREME"


def test_quality_gate_good_face(base_detection):
    qg = QualityGate(min_laplacian_var=10.0, min_brightness=40.0, max_brightness=220.0)
    # Sharp texture
    np.random.seed(42)
    sharp_crop = np.random.randint(60, 200, (112, 112, 3), dtype=np.uint8)
    report = qg.evaluate(frame=sharp_crop, detections=[base_detection], aligned_crop=sharp_crop)

    assert report.passed is True
    assert report.failure_code is None
