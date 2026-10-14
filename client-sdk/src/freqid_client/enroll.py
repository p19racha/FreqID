# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
enroll.py: Multi-capture guided enrollment coordinator.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from freqid_client.camera import CameraSource
from freqid_client.pipeline import ClientPipeline


@dataclass(frozen=True)
class EnrollmentProgress:
    """Structured progress update emitted to client UI/kiosk during enrollment."""
    frames_captured: int
    target_frames: int
    status: str  # "CAPTURING", "FRAME_ACCEPTED", "FRAME_REJECTED", "COMPLETED"
    prompt_message: str  # e.g. "Hold steady", "Move closer", "Face the camera"
    quality_code: str | None = None


class EnrollmentCoordinator:
    """
    Guides multi-capture facial enrollment, gathering K high-quality distinct frames.
    """

    def __init__(
        self,
        pipeline: ClientPipeline,
        target_frames: int = 5,
        min_interval_seconds: float = 0.3,
    ) -> None:
        self.pipeline = pipeline
        self.target_frames = target_frames
        self.min_interval_seconds = min_interval_seconds

    def enroll(
        self,
        camera: CameraSource,
        progress_callback: Callable[[EnrollmentProgress], None] | None = None,
        max_attempts: int = 50,
    ) -> list[bytes]:
        """
        Gathers target_frames payloads from the camera.

        Returns:
            List of binary payload bytes.
        """
        captured_payloads: list[bytes] = []
        last_capture_time = 0.0
        attempts = 0

        def _notify(status: str, msg: str, q_code: str | None = None) -> None:
            if progress_callback:
                progress_callback(
                    EnrollmentProgress(
                        frames_captured=len(captured_payloads),
                        target_frames=self.target_frames,
                        status=status,
                        prompt_message=msg,
                        quality_code=q_code,
                    )
                )

        _notify("CAPTURING", "Position yourself in front of the camera...")

        while len(captured_payloads) < self.target_frames and attempts < max_attempts:
            frame = camera.read_frame()
            if frame is None:
                time.sleep(0.05)
                continue
            attempts += 1

            now = time.perf_counter()
            if (now - last_capture_time) < self.min_interval_seconds:
                continue

            result = self.pipeline.process_frame(frame)
            if not result.success:
                code = result.rejection_reason or "UNKNOWN"
                msg = result.quality_report.failure_message or "Quality check failed."
                _notify("FRAME_REJECTED", msg, q_code=code)
                continue

            # Accepted frame
            assert result.payload_bytes is not None
            captured_payloads.append(result.payload_bytes)
            last_capture_time = now

            if len(captured_payloads) < self.target_frames:
                _notify(
                    "FRAME_ACCEPTED",
                    f"Frame {len(captured_payloads)}/{self.target_frames} captured. Hold steady...",
                )
            else:
                _notify(
                    "COMPLETED",
                    f"All {self.target_frames} enrollment frames captured successfully.",
                )

        if len(captured_payloads) < self.target_frames:
            raise RuntimeError(
                f"Enrollment timed out: captured only {len(captured_payloads)}/{self.target_frames} frames."
            )

        return captured_payloads
