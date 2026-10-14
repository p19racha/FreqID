# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_pipeline.py: Unit tests for ClientPipeline orchestration and memory-only execution.
"""

import numpy as np

from freqid_client.config import ClientConfig
from freqid_client.detect import FaceDetection, FaceDetector
from freqid_client.pipeline import ClientPipeline


class MockDetector(FaceDetector):
    """Deterministic mock detector returning synthetic face landmarks."""

    def __init__(self, should_detect: bool = True) -> None:
        self.should_detect = should_detect

    def detect(self, frame: np.ndarray) -> list[FaceDetection]:
        if not self.should_detect:
            return []
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


def test_pipeline_successful_run():
    # Textured frame that passes quality gate
    np.random.seed(42)
    frame = np.random.randint(60, 200, (320, 320, 3), dtype=np.uint8)

    cfg = ClientConfig(min_laplacian_var=10.0, compress_payload=True)
    pipeline = ClientPipeline(config=cfg, detector=MockDetector(should_detect=True))

    result = pipeline.process_frame(frame, subset_index=0, perm_index=0)

    assert result.success is True
    assert result.payload_bytes is not None
    assert result.payload_size_bytes > 10_000
    assert result.timings.total_ms > 0
    assert result.timings.transform_ms > 0
    assert result.rejection_reason is None


def test_pipeline_no_face_rejection():
    frame = np.full((320, 320, 3), 128, dtype=np.uint8)
    pipeline = ClientPipeline(detector=MockDetector(should_detect=False))

    result = pipeline.process_frame(frame)

    assert result.success is False
    assert result.payload_bytes is None
    assert result.rejection_reason == "NO_FACE_DETECTED"


def test_pipeline_timings_recorded():
    np.random.seed(42)
    frame = np.random.randint(60, 200, (320, 320, 3), dtype=np.uint8)

    cfg = ClientConfig(min_laplacian_var=10.0)
    pipeline = ClientPipeline(config=cfg, detector=MockDetector(should_detect=True))

    result = pipeline.process_frame(frame)
    t = result.timings

    assert t.detect_ms >= 0
    assert t.align_ms >= 0
    assert t.quality_ms >= 0
    assert t.transform_ms >= 0
    assert t.serialize_ms >= 0
    assert t.total_ms >= (t.detect_ms + t.align_ms + t.transform_ms)
