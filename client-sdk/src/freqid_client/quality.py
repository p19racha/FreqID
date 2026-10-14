# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
quality.py: Multi-criterion facial image quality gate and rejection diagnostic engine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from freqid_client.detect import FaceDetection


@dataclass(frozen=True)
class QualityReport:
    """Diagnostic report detailing the evaluation outcome of the quality gate."""
    passed: bool
    failure_code: str | None
    failure_message: str | None
    blur_score: float
    brightness_score: float
    face_size: tuple[float, float]
    yaw_angle_deg: float


class QualityGate:
    """
    Evaluates detected face frames against sharpness, illumination, resolution, and pose thresholds.
    """

    def __init__(
        self,
        min_face_size: int = 60,
        min_laplacian_var: float = 80.0,
        min_brightness: float = 40.0,
        max_brightness: float = 220.0,
        max_yaw_angle: float = 15.0,
        allow_multiple_faces: bool = False,
    ) -> None:
        self.min_face_size = min_face_size
        self.min_laplacian_var = min_laplacian_var
        self.min_brightness = min_brightness
        self.max_brightness = max_brightness
        self.max_yaw_angle = max_yaw_angle
        self.allow_multiple_faces = allow_multiple_faces

    def evaluate(
        self,
        frame: np.ndarray,
        detections: list[FaceDetection],
        aligned_crop: np.ndarray | None = None,
    ) -> QualityReport:
        """
        Evaluates detection and face crop against quality gate rules.
        """
        # 1. Face Count Check
        if not detections:
            return QualityReport(
                passed=False,
                failure_code="NO_FACE_DETECTED",
                failure_message="No face detected in camera frame. Please position yourself in front of the camera.",
                blur_score=0.0,
                brightness_score=0.0,
                face_size=(0.0, 0.0),
                yaw_angle_deg=0.0,
            )

        if len(detections) > 1 and not self.allow_multiple_faces:
            return QualityReport(
                passed=False,
                failure_code="MULTIPLE_FACES_DETECTED",
                failure_message=f"Multiple faces detected ({len(detections)}). Only one person should be visible.",
                blur_score=0.0,
                brightness_score=0.0,
                face_size=(0.0, 0.0),
                yaw_angle_deg=0.0,
            )

        primary_face = detections[0]
        w, h = primary_face.width, primary_face.height

        # 2. Face Size Check
        if min(w, h) < self.min_face_size:
            return QualityReport(
                passed=False,
                failure_code="FACE_TOO_SMALL",
                failure_message=f"Face is too far from camera ({w:.0f}x{h:.0f}px, min {self.min_face_size}px). Please move closer.",
                blur_score=0.0,
                brightness_score=0.0,
                face_size=(w, h),
                yaw_angle_deg=0.0,
            )

        # 3. Pose Check (Yaw angle estimation from 5 landmarks)
        lmks = primary_face.landmarks
        left_eye, right_eye = lmks[0], lmks[1]
        nose = lmks[2]
        _left_mouth, _right_mouth = lmks[3], lmks[4]

        eye_dx = float(right_eye[0] - left_eye[0])
        eye_dy = float(right_eye[1] - left_eye[1])
        roll_deg = abs(math.degrees(math.atan2(eye_dy, eye_dx)))

        # Yaw estimation from nose position relative to eye midpoint
        eye_midpoint_x = (left_eye[0] + right_eye[0]) / 2.0
        eye_dist = max(math.hypot(eye_dx, eye_dy), 1.0)
        nose_offset_ratio = abs(nose[0] - eye_midpoint_x) / eye_dist
        estimated_yaw_deg = nose_offset_ratio * 45.0  # Linear approximation

        if estimated_yaw_deg > self.max_yaw_angle or roll_deg > 25.0:
            return QualityReport(
                passed=False,
                failure_code="POSE_TOO_EXTREME",
                failure_message="Face is tilted or turned away. Please look directly into the camera.",
                blur_score=0.0,
                brightness_score=0.0,
                face_size=(w, h),
                yaw_angle_deg=estimated_yaw_deg,
            )

        # 4. Blur & Brightness Checks (evaluated on aligned crop or bbox crop)
        if aligned_crop is not None:
            eval_crop = aligned_crop
        else:
            x_min = max(0, int(primary_face.bbox[0]))
            y_min = max(0, int(primary_face.bbox[1]))
            x_max = min(frame.shape[1], int(primary_face.bbox[0] + w))
            y_max = min(frame.shape[0], int(primary_face.bbox[1] + h))
            eval_crop = frame[y_min:y_max, x_min:x_max]

        if eval_crop.size == 0:
            return QualityReport(
                passed=False,
                failure_code="EMPTY_CROP",
                failure_message="Cropped face region is empty.",
                blur_score=0.0,
                brightness_score=0.0,
                face_size=(w, h),
                yaw_angle_deg=estimated_yaw_deg,
            )

        # Convert to grayscale for blur and illumination calculation
        gray = cv2.cvtColor(eval_crop, cv2.COLOR_BGR2GRAY) if eval_crop.ndim == 3 else eval_crop
        mean_brightness = float(np.mean(gray))
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # 4. Illumination checks (evaluated before blur so underexposed/overexposed frames get actionable feedback)
        if mean_brightness < self.min_brightness:
            return QualityReport(
                passed=False,
                failure_code="IMAGE_TOO_DARK",
                failure_message=f"Environment is too dark (brightness {mean_brightness:.1f}, min {self.min_brightness}). Increase lighting.",
                blur_score=laplacian_var,
                brightness_score=mean_brightness,
                face_size=(w, h),
                yaw_angle_deg=estimated_yaw_deg,
            )

        if mean_brightness > self.max_brightness:
            return QualityReport(
                passed=False,
                failure_code="IMAGE_TOO_BRIGHT",
                failure_message=f"Image is overexposed (brightness {mean_brightness:.1f}, max {self.max_brightness}). Avoid direct glare.",
                blur_score=laplacian_var,
                brightness_score=mean_brightness,
                face_size=(w, h),
                yaw_angle_deg=estimated_yaw_deg,
            )

        # 5. Sharpness / Blur check
        if laplacian_var < self.min_laplacian_var:
            return QualityReport(
                passed=False,
                failure_code="IMAGE_TOO_BLURRY",
                failure_message=f"Image is blurry (score {laplacian_var:.1f}, min {self.min_laplacian_var}). Hold steady.",
                blur_score=laplacian_var,
                brightness_score=mean_brightness,
                face_size=(w, h),
                yaw_angle_deg=estimated_yaw_deg,
            )

        # Passed all checks
        return QualityReport(
            passed=True,
            failure_code=None,
            failure_message=None,
            blur_score=laplacian_var,
            brightness_score=mean_brightness,
            face_size=(w, h),
            yaw_angle_deg=estimated_yaw_deg,
        )
