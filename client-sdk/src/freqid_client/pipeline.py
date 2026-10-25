# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
pipeline.py: In-memory client pipeline orchestrating detection, alignment, quality gating,
frequency transformation, and wire payload packaging.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import freqid_core as fq
import numpy as np
from freqid_core.transform import image_to_partial_frequency

from freqid_client.align import align_face
from freqid_client.camera import CameraSource
from freqid_client.config import ClientConfig
from freqid_client.detect import FaceDetection, FaceDetector, YuNetFaceDetector
from freqid_client.quality import QualityGate, QualityReport


@dataclass(frozen=True)
class PipelineTimings:
    """Detailed latency metrics (in milliseconds) for each edge processing stage."""

    detect_ms: float
    align_ms: float
    quality_ms: float
    transform_ms: float
    serialize_ms: float
    total_ms: float


@dataclass(frozen=True)
class PipelineResult:
    """The outcome of processing a single camera frame through the edge pipeline."""

    success: bool
    payload_bytes: bytes | None
    quality_report: QualityReport
    detection: FaceDetection | None
    timings: PipelineTimings
    rejection_reason: str | None = None
    payload_size_bytes: int = 0


class ClientPipeline:
    """
    Orchestrates the privacy-preserving edge pipeline.

    PRIVACY GUARANTEE:
    Raw spatial video frames and aligned facial crops reside in transient RAM only.
    As soon as the partial frequency representation is created, spatial buffers are
    cleared. No unencrypted facial imagery is persisted to disk or sent over network.
    """

    def __init__(
        self,
        config: ClientConfig | None = None,
        detector: FaceDetector | None = None,
    ) -> None:
        self.config = config or ClientConfig()
        self.detector = detector or YuNetFaceDetector(
            model_path=self.config.detector_model_path,
            score_threshold=self.config.detector_score_threshold,
            nms_threshold=self.config.detector_nms_threshold,
        )
        self.quality_gate = QualityGate(
            min_face_size=self.config.min_face_size,
            min_laplacian_var=self.config.min_laplacian_var,
            min_brightness=self.config.min_brightness,
            max_brightness=self.config.max_brightness,
            max_yaw_angle=self.config.max_yaw_angle,
            allow_multiple_faces=self.config.allow_multiple_faces,
        )

    def process_frame(
        self,
        frame: np.ndarray,
        subset_index: int | None = None,
        perm_index: int | None = None,
        rng: np.random.Generator | int | None = None,
    ) -> PipelineResult:
        """
        Executes end-to-end edge pipeline on a single frame.

        Args:
            frame: Raw BGR uint8 camera frame.
            subset_index: Optional deterministic subset [0..5] (default: secure random).
            perm_index: Optional deterministic permutation [0..2] (default: secure random).
            rng: Optional RNG seed/generator for tests.

        Returns:
            PipelineResult containing payload_bytes on success, or rejection_reason on failure.
        """
        t_start = time.perf_counter()

        # 1. Detection
        t0 = time.perf_counter()
        detections = self.detector.detect(frame)
        t_detect = (time.perf_counter() - t0) * 1000.0

        if not detections:
            q_rep = self.quality_gate.evaluate(frame, detections)
            timings = PipelineTimings(
                detect_ms=t_detect,
                align_ms=0.0,
                quality_ms=0.0,
                transform_ms=0.0,
                serialize_ms=0.0,
                total_ms=(time.perf_counter() - t_start) * 1000.0,
            )
            return PipelineResult(
                success=False,
                payload_bytes=None,
                quality_report=q_rep,
                detection=None,
                timings=timings,
                rejection_reason=q_rep.failure_code,
            )

        primary_face = detections[0]

        # 2. Alignment & Cropping
        t0 = time.perf_counter()
        try:
            aligned_bgr = align_face(
                frame=frame,
                landmarks=primary_face.landmarks,
                crop_size=self.config.crop_size,
            )
        except Exception as e:  # noqa: BLE001
            q_rep = QualityReport(
                passed=False,
                failure_code="ALIGNMENT_FAILED",
                failure_message=f"Facial alignment failed: {e}",
                blur_score=0.0,
                brightness_score=0.0,
                face_size=(primary_face.width, primary_face.height),
                yaw_angle_deg=0.0,
            )
            timings = PipelineTimings(
                detect_ms=t_detect,
                align_ms=(time.perf_counter() - t0) * 1000.0,
                quality_ms=0.0,
                transform_ms=0.0,
                serialize_ms=0.0,
                total_ms=(time.perf_counter() - t_start) * 1000.0,
            )
            return PipelineResult(
                success=False,
                payload_bytes=None,
                quality_report=q_rep,
                detection=primary_face,
                timings=timings,
                rejection_reason="ALIGNMENT_FAILED",
            )
        t_align = (time.perf_counter() - t0) * 1000.0

        # 3. Quality Gate
        t0 = time.perf_counter()
        q_rep = self.quality_gate.evaluate(
            frame=frame,
            detections=detections,
            aligned_crop=aligned_bgr,
        )
        t_quality = (time.perf_counter() - t0) * 1000.0

        if not q_rep.passed:
            # Overwrite transient crop
            aligned_bgr.fill(0)
            timings = PipelineTimings(
                detect_ms=t_detect,
                align_ms=t_align,
                quality_ms=t_quality,
                transform_ms=0.0,
                serialize_ms=0.0,
                total_ms=(time.perf_counter() - t_start) * 1000.0,
            )
            return PipelineResult(
                success=False,
                payload_bytes=None,
                quality_report=q_rep,
                detection=primary_face,
                timings=timings,
                rejection_reason=q_rep.failure_code,
            )

        # Convert to RGB for frequency transformation
        aligned_rgb = cv2.cvtColor(aligned_bgr, cv2.COLOR_BGR2RGB)

        # Optional debug save directory (prints warning if set)
        if self.config.debug_save_dir:
            debug_path = Path(self.config.debug_save_dir)
            debug_path.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(
                str(debug_path / f"debug_aligned_{int(time.time() * 1000)}.png"), aligned_bgr
            )

        # 4. Frequency Domain Transformation (Pure-NumPy engine, zero torch dependency)
        t0 = time.perf_counter()
        freq_array = image_to_partial_frequency(
            image=aligned_rgb,
            subset_index=subset_index,
            perm_index=perm_index,
            rng=rng,
            engine="numpy",
        )
        t_transform = (time.perf_counter() - t0) * 1000.0

        # Discard spatial crop immediately
        aligned_bgr.fill(0)
        aligned_rgb.fill(0)
        del aligned_bgr
        del aligned_rgb

        # 5. Wire Payload Serialization
        t0 = time.perf_counter()
        payload = fq.PartialFacePayload(
            data=freq_array,
            subset_index=subset_index if subset_index is not None else -1,
            perm_index=perm_index if perm_index is not None else -1,
        )
        payload_bytes = payload.to_bytes(compress=self.config.compress_payload)
        t_serialize = (time.perf_counter() - t0) * 1000.0

        t_total = (time.perf_counter() - t_start) * 1000.0
        timings = PipelineTimings(
            detect_ms=t_detect,
            align_ms=t_align,
            quality_ms=t_quality,
            transform_ms=t_transform,
            serialize_ms=t_serialize,
            total_ms=t_total,
        )

        return PipelineResult(
            success=True,
            payload_bytes=payload_bytes,
            quality_report=q_rep,
            detection=primary_face,
            timings=timings,
            rejection_reason=None,
            payload_size_bytes=len(payload_bytes),
        )

    def capture_best_frame(
        self,
        camera_source: CameraSource | Any,
        window_frames: int = 5,
        max_attempts: int = 15,
    ) -> PipelineResult:
        """
        Captures up to window_frames, filters through quality gate, and selects
        the best-quality frame (highest sharpness score).
        """
        best_result: PipelineResult | None = None
        best_score = -1.0
        attempts = 0

        while attempts < max_attempts:
            frame = camera_source.read_frame()
            if frame is None:
                break
            attempts += 1

            result = self.process_frame(frame)
            if result.success:
                score = result.quality_report.blur_score
                if score > best_score:
                    best_score = score
                    best_result = result

                if attempts >= window_frames and best_result is not None:
                    break

        if best_result is not None:
            return best_result

        # If no frame succeeded, return the last rejected attempt
        if "result" in locals():
            return result
        raise RuntimeError("Camera source produced no frames.")
