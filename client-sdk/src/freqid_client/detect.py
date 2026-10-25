# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
detect.py: Pluggable face detection interface and OpenCV YuNet implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from freqid_client.errors import DetectionError


@dataclass(frozen=True)
class FaceDetection:
    """Encapsulates a single detected face bounding box and 5 facial landmarks."""

    bbox: tuple[float, float, float, float]  # (x, y, w, h)
    score: float
    landmarks: np.ndarray  # Shape (5, 2): [left_eye, right_eye, nose, left_mouth, right_mouth]

    @property
    def width(self) -> float:
        return self.bbox[2]

    @property
    def height(self) -> float:
        return self.bbox[3]

    @property
    def area(self) -> float:
        return self.width * self.height


class FaceDetector(ABC):
    """Abstract interface for edge face detectors."""

    @abstractmethod
    def detect(self, frame: np.ndarray) -> list[FaceDetection]:
        """
        Detect faces in a BGR or RGB image.

        Args:
            frame: Image array of shape (H, W, 3).

        Returns:
            List of FaceDetection objects sorted by confidence score (descending).
        """


class YuNetFaceDetector(FaceDetector):
    """
    Lightweight CPU face detector powered by OpenCV's YuNet ONNX model (Apache-2.0).
    Produces 5 facial landmarks for alignment with ~5-10ms CPU latency.
    """

    def __init__(
        self,
        model_path: str | Path,
        score_threshold: float = 0.6,
        nms_threshold: float = 0.3,
        top_k: int = 5000,
    ) -> None:
        p = Path(model_path)
        if not p.is_file():
            raise DetectionError(f"YuNet model weights not found at: {model_path}")

        self.model_path = str(p)
        self.score_threshold = float(score_threshold)
        self.nms_threshold = float(nms_threshold)
        self.top_k = int(top_k)

        # Default size, dynamically adjusted per frame
        self._current_size = (320, 320)
        try:
            self._detector = cv2.FaceDetectorYN.create(
                model=self.model_path,
                config="",
                input_size=self._current_size,
                score_threshold=self.score_threshold,
                nms_threshold=self.nms_threshold,
                top_k=self.top_k,
            )
        except Exception as e:
            raise DetectionError(f"Failed to initialize cv2.FaceDetectorYN: {e}") from e

    def detect(self, frame: np.ndarray) -> list[FaceDetection]:
        if frame is None or frame.size == 0:
            return []

        h, w = frame.shape[:2]
        if (w, h) != self._current_size:
            self._current_size = (w, h)
            self._detector.setInputSize(self._current_size)

        try:
            _, faces = self._detector.detect(frame)
        except Exception as e:
            raise DetectionError(f"YuNet face detection execution failed: {e}") from e

        if faces is None or len(faces) == 0:
            return []

        detections: list[FaceDetection] = []
        for face in faces:
            # Face format: [x, y, w, h, x_re, y_re, x_le, y_le, x_nt, y_nt, x_rcm, y_rcm, x_lcm, y_lcm, score]
            bbox = (float(face[0]), float(face[1]), float(face[2]), float(face[3]))
            lmks = np.array(face[4:14], dtype=np.float32).reshape((5, 2))
            score = float(face[-1])
            detections.append(FaceDetection(bbox=bbox, score=score, landmarks=lmks))

        # Sort by confidence score descending
        detections.sort(key=lambda d: d.score, reverse=True)
        return detections
