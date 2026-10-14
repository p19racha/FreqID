# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
align.py: Landmark-based similarity transform and 112x112 facial alignment.

Cites reference points directly from Tencent/TFace:
Source: recognition/test/datasets.py, lines 22-33
        recognition/tools/img2tfrecord.py, lines 49-65
"""

from __future__ import annotations

import cv2
import numpy as np

from freqid_client.errors import AlignmentError

# 5-point standard reference template from Tencent/TFace and InsightFace
# Derived from 112x112 canonical facial coordinate frame with +8px horizontal shift:
# [30.2946 + 8.0, 51.6963], [65.5318 + 8.0, 51.5014], [48.0252 + 8.0, 71.7366],
# [33.5493 + 8.0, 92.3655], [62.7299 + 8.0, 92.2041]
REFERENCE_5_POINTS = np.array(
    [
        [38.2946, 51.6963],  # Left Eye (from viewer perspective)
        [73.5318, 51.5014],  # Right Eye (from viewer perspective)
        [56.0252, 71.7366],  # Nose Tip
        [41.5493, 92.3655],  # Left Mouth Corner
        [70.7299, 92.2041],  # Right Mouth Corner
    ],
    dtype=np.float32,
)


def estimate_similarity_transform(
    src_pts: np.ndarray,
    dst_pts: np.ndarray = REFERENCE_5_POINTS,
) -> np.ndarray:
    """
    Computes optimal 2D similarity transform matrix M (2x3) using Umeyama's algorithm.

    Finds scale s, rotation R, and translation t minimizing:
        || dst_pts - (s * R @ src_pts + t) ||^2

    Returns:
        np.ndarray of shape (2, 3) suitable for cv2.warpAffine.
    """
    src = np.asarray(src_pts, dtype=np.float64)
    dst = np.asarray(dst_pts, dtype=np.float64)

    if src.shape != (5, 2) or dst.shape != (5, 2):
        raise AlignmentError(f"Expected 5x2 landmarks arrays, got src={src.shape}, dst={dst.shape}")

    num_points = src.shape[0]
    dim = src.shape[1]

    src_mean = np.mean(src, axis=0)
    dst_mean = np.mean(dst, axis=0)

    src_demean = src - src_mean
    dst_demean = dst - dst_mean

    src_var = np.sum(src_demean**2) / num_points
    if src_var < 1e-8:
        raise AlignmentError("Degenerate landmark coordinates: source variance near zero.")

    # Cross-covariance matrix
    cov = (dst_demean.T @ src_demean) / num_points

    u, s, vt = np.linalg.svd(cov)
    r = u @ vt

    # Reflection check
    if np.linalg.det(r) < 0:
        d = np.eye(dim)
        d[-1, -1] = -1
        r = u @ d @ vt
        s[-1] *= -1

    scale = np.sum(s) / src_var
    trans = dst_mean - scale * (r @ src_mean)

    m = np.zeros((2, 3), dtype=np.float32)
    m[0:2, 0:2] = scale * r
    m[0:2, 2] = trans

    return m


def align_face(
    frame: np.ndarray,
    landmarks: np.ndarray,
    crop_size: tuple[int, int] = (112, 112),
) -> np.ndarray:
    """
    Aligns and crops a detected face to 112x112 using 5-point similarity transformation.

    Args:
        frame: Input image array (H, W, 3).
        landmarks: Array of shape (5, 2) with facial landmarks.
        crop_size: Output dimensions (width, height), default (112, 112).

    Returns:
        Cropped and aligned face image of shape (112, 112, 3).
    """
    if frame is None or frame.size == 0:
        raise AlignmentError("Input frame is empty.")

    m = estimate_similarity_transform(src_pts=landmarks)
    aligned = cv2.warpAffine(
        frame,
        m,
        crop_size,
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    return aligned
