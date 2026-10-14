# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
camera.py: Camera source abstractions for live webcams, video files, and test image folders.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import cv2
import numpy as np

from freqid_client.errors import CameraError


class CameraSource(ABC):
    """Abstract interface for video capture sources."""

    @abstractmethod
    def open(self) -> None:
        """Open the video device or file stream."""

    @abstractmethod
    def read_frame(self) -> np.ndarray | None:
        """Reads a single frame in BGR uint8 format. Returns None if end of stream."""

    @abstractmethod
    def release(self) -> None:
        """Release underlying hardware or file descriptors."""

    def __enter__(self) -> CameraSource:  # noqa: PYI034
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self.release()


class WebcamSource(CameraSource):
    """Captures live frames from a local USB/integrated UVC camera via OpenCV."""

    def __init__(
        self,
        camera_index: int = 0,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
    ) -> None:
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.fps = fps
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        self._cap = cv2.VideoCapture(self.camera_index)
        if not self._cap.isOpened():
            raise CameraError(f"Failed to open video capture device at index {self.camera_index}")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._cap.set(cv2.CAP_PROP_FPS, self.fps)

    def read_frame(self) -> np.ndarray | None:
        if self._cap is None or not self._cap.isOpened():
            raise CameraError("Cannot read from closed camera device.")
        ret, frame = self._cap.read()
        if not ret:
            return None
        return frame

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class SingleImageSource(CameraSource):
    """Yields a single static image (from path or array). Useful for 1-shot checks and testing."""

    def __init__(self, image: str | Path | np.ndarray) -> None:
        if isinstance(image, (str, Path)):
            img = cv2.imread(str(image))
            if img is None:
                raise CameraError(f"Failed to read image from path: {image}")
            self._frame = img
        else:
            self._frame = np.asarray(image)
        self._read_count = 0

    def open(self) -> None:
        self._read_count = 0

    def read_frame(self) -> np.ndarray | None:
        if self._read_count == 0:
            self._read_count += 1
            return self._frame.copy()
        return None

    def release(self) -> None:
        pass


class ImageFolderSource(CameraSource):
    """
    Sequentially feeds images from a local directory.
    Critical for reproducible headless automated testing and CI pipelines.
    """

    def __init__(self, folder_path: str | Path, loop: bool = False) -> None:
        self.folder_path = Path(folder_path)
        self.loop = loop
        if not self.folder_path.is_dir():
            raise CameraError(f"Image folder not found: {folder_path}")

        valid_exts = {".jpg", ".jpeg", ".png", ".bmp"}
        self._files = sorted(
            [f for f in self.folder_path.iterdir() if f.suffix.lower() in valid_exts]
        )
        if not self._files:
            raise CameraError(f"No image files found in {folder_path}")
        self._idx = 0

    def open(self) -> None:
        self._idx = 0

    def read_frame(self) -> np.ndarray | None:
        if self._idx >= len(self._files):
            if self.loop:
                self._idx = 0
            else:
                return None

        img_path = self._files[self._idx]
        self._idx += 1
        frame = cv2.imread(str(img_path))
        return frame

    def release(self) -> None:
        pass
