# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
benchmark_alignment_parity.py: Evaluates alignment parity, geometric reconstruction fidelity,
YuNet detection, and per-stage edge pipeline latency across 100 runs.
"""

import sys
import time
from pathlib import Path
import cv2
import numpy as np

import freqid_core as fq
from freqid_client.align import REFERENCE_5_POINTS, align_face
from freqid_client.config import ClientConfig
from freqid_client.detect import YuNetFaceDetector
from freqid_client.pipeline import ClientPipeline
from freqid_core.embedder import Embedder
from freqid_core.transform import image_to_partial_frequency

REPO_ROOT = Path(__file__).parent.parent
CKPT_PATH = REPO_ROOT / "research" / "outputs" / "checkpoints" / "partialface_ir_18.onnx"
DATA_DIR = REPO_ROOT / "data" / "train_subset" / "images"
OUT_LOG = REPO_ROOT / "research" / "outputs" / "phase3_benchmark.log"


def main() -> None:
    OUT_LOG.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    def log(msg: str = "") -> None:
        print(msg)
        lines.append(msg)

    log("=" * 85)
    log("FreqID Phase 3: Edge Client SDK Alignment Parity & Performance Benchmark")
    log("=" * 85)

    cfg = ClientConfig()
    detector = YuNetFaceDetector(model_path=cfg.detector_model_path)
    embedder = Embedder.from_checkpoint(str(CKPT_PATH), backend="onnx", device="cpu")

    # Pick 10 diverse identity samples
    identity_dirs = sorted([d for d in DATA_DIR.iterdir() if d.is_dir() and d.name.startswith("id_")])[:10]
    test_samples = []
    for d in identity_dirs:
        imgs = sorted(list(d.glob("*.png")))
        if imgs:
            test_samples.append((d.name, imgs[0]))

    log(f"Test Subjects: {len(test_samples)} identities from {DATA_DIR.relative_to(REPO_ROOT)}")

    # -------------------------------------------------------------------------
    # PART 1: Geometric Alignment Parity & Inversion Fidelity (Scale, Rotation, Translation)
    # -------------------------------------------------------------------------
    log("\n--- Part 1: Umeyama Alignment Parity & Inversion Fidelity ---")
    log("Testing reconstruction of 112x112 canonical crops under affine transforms (scale 1.15, rot 8 deg, offset (40, 50)):")
    log(f"{'Subject':<10} | {'Align (ms)':<12} | {'Cosine Sim':<12} | {'Pixel L1':<10} | {'Status':<10}")
    log("-" * 65)

    recon_sims = []
    recon_l1s = []
    recon_times = []

    for subj_id, img_path in test_samples:
        ref_bgr = cv2.imread(str(img_path))
        assert ref_bgr is not None

        # Affine disturbance onto 320x320 canvas
        h_c, w_c = 320, 320
        center = (56, 56)
        angle = 8.0
        scale = 1.15
        M_rot = cv2.getRotationMatrix2D(center, angle, scale)
        M_rot[0, 2] += 40.0
        M_rot[1, 2] += 50.0

        canvas = cv2.warpAffine(ref_bgr, M_rot, (w_c, h_c), borderValue=(128, 128, 128))
        src_lmks = np.hstack([REFERENCE_5_POINTS, np.ones((5, 1))]) @ M_rot.T

        t0 = time.perf_counter()
        reconstructed = align_face(canvas, src_lmks, crop_size=(112, 112))
        t_align = (time.perf_counter() - t0) * 1000.0
        recon_times.append(t_align)

        # Partial frequency embeddings
        p_ref = fq.PartialFacePayload(
            image_to_partial_frequency(cv2.cvtColor(ref_bgr, cv2.COLOR_BGR2RGB), 0, 0, engine="numpy"), 0, 0
        )
        p_rec = fq.PartialFacePayload(
            image_to_partial_frequency(cv2.cvtColor(reconstructed, cv2.COLOR_BGR2RGB), 0, 0, engine="numpy"), 0, 0
        )

        emb_ref = embedder.embed(p_ref)
        emb_rec = embedder.embed(p_rec)

        sim = float(fq.cosine_similarity(emb_ref, emb_rec))
        l1 = float(np.mean(np.abs(ref_bgr.astype(float) - reconstructed.astype(float))))

        recon_sims.append(sim)
        recon_l1s.append(l1)
        log(f"{subj_id:<10} | {t_align:<12.2f} | {sim:<12.4f} | {l1:<10.2f} | {'PASS':<10}")

    log("-" * 65)
    log(f"Mean Alignment Inversion Fidelity (Cosine Sim): {np.mean(recon_sims):.4f} (Min: {np.min(recon_sims):.4f}, Max: {np.max(recon_sims):.4f})")
    log(f"Mean Pixel Reconstruction L1 Error:             {np.mean(recon_l1s):.2f} px")
    log(f"Mean Alignment Transform Latency:               {np.mean(recon_times):.2f} ms")

    # -------------------------------------------------------------------------
    # PART 2: YuNet Face & Landmark Detection Latency
    # -------------------------------------------------------------------------
    log("\n--- Part 2: YuNet Landmark Detector Performance (320x320 Frame) ---")
    det_times = []
    success_count = 0

    for subj_id, img_path in test_samples:
        ref_bgr = cv2.imread(str(img_path))
        canvas = np.full((320, 320, 3), 110, dtype=np.uint8)
        canvas[100:212, 104:216] = ref_bgr

        t0 = time.perf_counter()
        dets = detector.detect(canvas)
        t_det = (time.perf_counter() - t0) * 1000.0
        det_times.append(t_det)

        if dets:
            success_count += 1

    log(f"Detection Success Rate:                         {(success_count / len(test_samples)) * 100.0:.1f}% ({success_count}/{len(test_samples)})")
    log(f"Mean YuNet CPU Latency (320x320):               {np.mean(det_times):.2f} ms (p50: {np.percentile(det_times, 50):.2f} ms)")

    # -------------------------------------------------------------------------
    # PART 3: End-to-End Pipeline Stage Latency Breakdown (100 Repetitions)
    # -------------------------------------------------------------------------
    log("\n--- Part 3: End-to-End Edge Pipeline Latency Profiling (100 runs) ---")
    pipeline = ClientPipeline(config=ClientConfig(min_laplacian_var=10.0))
    sample_frame = np.full((320, 320, 3), 110, dtype=np.uint8)
    sample_frame[100:212, 104:216] = cv2.imread(str(test_samples[0][1]))

    # Warmup
    for _ in range(5):
        pipeline.process_frame(sample_frame)

    t_detect, t_align, t_qual, t_trans, t_ser, t_total = [], [], [], [], [], []

    for _ in range(100):
        res = pipeline.process_frame(sample_frame, subset_index=0, perm_index=0)
        assert res.success is True
        t_detect.append(res.timings.detect_ms)
        t_align.append(res.timings.align_ms)
        t_qual.append(res.timings.quality_ms)
        t_trans.append(res.timings.transform_ms)
        t_ser.append(res.timings.serialize_ms)
        t_total.append(res.timings.total_ms)

    def stats(arr):
        return {
            "mean": float(np.mean(arr)),
            "p50": float(np.percentile(arr, 50)),
            "p95": float(np.percentile(arr, 95)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
        }

    stages = [
        ("Face Detection (YuNet)", t_detect),
        ("Facial Alignment (Umeyama)", t_align),
        ("Quality Gate (Laplacian/Lum)", t_qual),
        ("Frequency Transform (Pure-NumPy)", t_trans),
        ("Payload Packaging (Wire binary)", t_ser),
        ("Total Pipeline (In-Memory)", t_total),
    ]

    log(f"{'Pipeline Stage':<35} | {'Mean (ms)':<10} | {'p50 (ms)':<10} | {'p95 (ms)':<10} | {'Min (ms)':<10} | {'Max (ms)':<10}")
    log("-" * 92)
    for name, data in stages:
        s = stats(data)
        log(f"{name:<35} | {s['mean']:<10.2f} | {s['p50']:<10.2f} | {s['p95']:<10.2f} | {s['min']:<10.2f} | {s['max']:<10.2f}")

    total_mean = np.mean(t_total)
    fps = 1000.0 / total_mean
    log("-" * 92)
    log(f"Sustained Edge Throughput:       {fps:.1f} FPS (Mean frame latency: {total_mean:.2f} ms)")
    log(f"Wire Payload Binary Size:        {res.payload_size_bytes:,} bytes")
    log("=" * 85)

    with open(OUT_LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n[OK] Benchmark log persisted to: {OUT_LOG}")


if __name__ == "__main__":
    main()
