#!/usr/bin/env python3
# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
enroll_and_verify.py: End-to-end demonstration of client transform, wire serialization,
server embedding, and 1:1 biometric verification on local images.
"""

import os
import sys
import cv2
import numpy as np

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "core", "src"))

import freqid_core as fq
from freqid_core.embedder import Embedder
from freqid_core.transform import image_to_partial_frequency


def client_capture_and_serialize(image_path: str, subset_idx: int = 0) -> bytes:
    """Simulates edge client: loads aligned face, applies BDCT & pruning, serializes payload."""
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Failed to read image at {image_path}")
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # 1. Transform spatial face to 27-channel partial frequency tensor
    freq_tensor = image_to_partial_frequency(rgb, subset_index=subset_idx, perm_index=0)

    # 2. Package into versioned binary payload
    payload = fq.PartialFacePayload(freq_tensor.numpy(), subset_index=subset_idx)

    # 3. Serialize to wire bytes (and discard raw spatial image)
    wire_bytes = payload.to_bytes(compress=True)
    return wire_bytes


def main():
    img_a1 = os.path.join(REPO_ROOT, "data", "train_subset", "images", "id_0000", "img_00.png")
    img_a2 = os.path.join(REPO_ROOT, "data", "train_subset", "images", "id_0000", "img_01.png")
    img_b1 = os.path.join(REPO_ROOT, "data", "train_subset", "images", "id_0001", "img_00.png")

    ckpt_path = os.path.join(REPO_ROOT, "research", "outputs", "checkpoints", "partialface_ir_18.onnx")
    if not os.path.exists(ckpt_path):
        ckpt_path = os.path.join(REPO_ROOT, "research", "outputs", "checkpoints", "partialface_ir_18_epoch5.pth")
        backend = "torch"
    else:
        backend = "onnx"

    print("=== FreqID End-to-End Enrollment & Verification Demo ===")
    print(f"Server Backend: {backend.upper()} ({ckpt_path})\n")

    # ------------------ Client-Side Processing ------------------
    print("[1/3] Client Edge Processing:")
    wire_a1 = client_capture_and_serialize(img_a1, subset_idx=0)
    wire_a2 = client_capture_and_serialize(img_a2, subset_idx=0)
    wire_b1 = client_capture_and_serialize(img_b1, subset_idx=0)

    print(f"  - Captured Person A (Img 1) -> Wire Payload: {len(wire_a1)} bytes (compressed)")
    print(f"  - Captured Person A (Img 2) -> Wire Payload: {len(wire_a2)} bytes (compressed)")
    print(f"  - Captured Person B (Img 1) -> Wire Payload: {len(wire_b1)} bytes (compressed)")
    print("  - [PRIVACY NOTE] Raw spatial images permanently discarded on client.\n")

    # ------------------ Server-Side Processing ------------------
    print("[2/3] Server-Side Deserialization & Feature Extraction:")
    embedder = Embedder.from_checkpoint(ckpt_path, backend=backend, device="cpu")

    payload_a1 = fq.PartialFacePayload.from_bytes(wire_a1)
    payload_a2 = fq.PartialFacePayload.from_bytes(wire_a2)
    payload_b1 = fq.PartialFacePayload.from_bytes(wire_b1)

    emb_a1 = embedder.embed(payload_a1)
    emb_a2 = embedder.embed(payload_a2)
    emb_b1 = embedder.embed(payload_b1)

    print(f"  - Extracted 512-D embedding A1 (L2 norm: {np.linalg.norm(emb_a1):.4f})")
    print(f"  - Extracted 512-D embedding A2 (L2 norm: {np.linalg.norm(emb_a2):.4f})")
    print(f"  - Extracted 512-D embedding B1 (L2 norm: {np.linalg.norm(emb_b1):.4f})\n")

    # ------------------ Biometric Matching ------------------
    print("[3/3] Biometric 1:1 Verification (Threshold = 0.35):")
    score_genuine, match_genuine = fq.verify(emb_a1, emb_a2, threshold=0.35)
    score_impostor, match_impostor = fq.verify(emb_a1, emb_b1, threshold=0.35)

    print(f"  [GENUINE PAIR]  Person A (Img 1) vs Person A (Img 2):")
    print(f"    Cosine Similarity: {score_genuine:.4f}")
    print(f"    Decision:          {'VERIFIED (Same Person)' if match_genuine else 'REJECTED'}")

    print(f"\n  [IMPOSTOR PAIR] Person A (Img 1) vs Person B (Img 1):")
    print(f"    Cosine Similarity: {score_impostor:.4f}")
    print(f"    Decision:          {'VERIFIED' if match_impostor else 'REJECTED (Different Person)'}")

    assert match_genuine is True, "Genuine pair failed to match!"
    assert match_impostor is False, "Impostor pair falsely accepted!"
    print("\n[SUCCESS] End-to-end enrollment and verification succeeded flawlessly.")


if __name__ == "__main__":
    main()
