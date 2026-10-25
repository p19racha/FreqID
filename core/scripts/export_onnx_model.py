#!/usr/bin/env python3
# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
export_onnx_model.py: Export PartialFace IR_18 backbone to ONNX and benchmark ONNX Runtime vs PyTorch.
"""

import os
import sys
import time

import numpy as np
import onnxruntime as ort
from onnxruntime.quantization import QuantType, quantize_dynamic

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "core", "src"))

from freqid_core.embedder import Embedder
from freqid_core.export_onnx import export_to_onnx, verify_onnx_export


def benchmark_session(session, batch_size, num_runs=30, warmup=5):
    input_name = session.get_inputs()[0].name
    dummy = np.random.randn(batch_size, 27, 112, 112).astype(np.float32)

    for _ in range(warmup):
        _ = session.run(None, {input_name: dummy})

    latencies = []
    for _ in range(num_runs):
        t0 = time.perf_counter()
        _ = session.run(None, {input_name: dummy})
        latencies.append((time.perf_counter() - t0) * 1000.0)

    avg_batch_ms = float(np.mean(latencies))
    avg_per_image_ms = avg_batch_ms / batch_size
    fps = 1000.0 / avg_per_image_ms
    return avg_per_image_ms, avg_batch_ms, fps


def main():
    ckpt_path = os.path.join(
        REPO_ROOT, "research", "outputs", "checkpoints", "partialface_ir_18_epoch5.pth"
    )
    onnx_path = os.path.join(
        REPO_ROOT, "research", "outputs", "checkpoints", "partialface_ir_18.onnx"
    )
    quant_onnx_path = os.path.join(
        REPO_ROOT, "research", "outputs", "checkpoints", "partialface_ir_18_int8.onnx"
    )
    log_file = os.path.join(REPO_ROOT, "core", "scripts", "onnx_export.log")

    print("=== Exporting PartialFace IR_18 to ONNX (Opset 14) ===")
    embedder = Embedder.from_checkpoint(ckpt_path, backend="torch", device="cpu")
    torch_model = embedder._model

    exported_path = export_to_onnx(
        model=torch_model,
        output_path=onnx_path,
        opset_version=14,
        dynamic_batch=True,
    )
    print(f"Exported ONNX model to: {exported_path}")

    onnx_file_size_mb = os.path.getsize(onnx_path) / (1024 * 1024)
    print(f"ONNX Model File Size: {onnx_file_size_mb:.2f} MB")

    # 1. Verification of mathematical parity
    print("\n--- Verifying ONNX Export Parity ---")
    max_diff = verify_onnx_export(torch_model, onnx_path, atol=1e-4)
    print(f"Max Absolute Error (PyTorch vs ONNX Runtime): {max_diff:.2e}")

    # 2. Benchmark ONNX Runtime FP32 on CPU
    print("\n--- Benchmarking ONNX Runtime (FP32, CPU) ---")
    session_fp32 = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    b1_per_img, b1_batch, b1_fps = benchmark_session(session_fp32, batch_size=1)
    b32_per_img, b32_batch, b32_fps = benchmark_session(session_fp32, batch_size=32)

    print(f"Batch Size 1:  {b1_per_img:.2f} ms/image ({b1_fps:.1f} FPS, {b1_batch:.2f} ms/batch)")
    print(
        f"Batch Size 32: {b32_per_img:.2f} ms/image ({b32_fps:.1f} FPS, {b32_batch:.2f} ms/batch)"
    )

    # 3. Dynamic INT8 Quantization Experiment
    print("\n--- Dynamic INT8 Quantization Experiment ---")
    quantize_dynamic(
        model_input=onnx_path,
        model_output=quant_onnx_path,
        weight_type=QuantType.QInt8,
    )
    quant_size_mb = os.path.getsize(quant_onnx_path) / (1024 * 1024)
    print(
        f"INT8 Quantized Model File Size: {quant_size_mb:.2f} MB (Compression: {(1 - quant_size_mb / onnx_file_size_mb) * 100:.1f}%)"
    )

    session_int8 = ort.InferenceSession(quant_onnx_path, providers=["CPUExecutionProvider"])
    q_b1_per_img, _, q_b1_fps = benchmark_session(session_int8, batch_size=1)
    q_b32_per_img, _, q_b32_fps = benchmark_session(session_int8, batch_size=32)

    print(f"INT8 Batch Size 1:  {q_b1_per_img:.2f} ms/image ({q_b1_fps:.1f} FPS)")
    print(f"INT8 Batch Size 32: {q_b32_per_img:.2f} ms/image ({q_b32_fps:.1f} FPS)")

    # Compare INT8 embeddings with FP32
    test_dummy = np.random.randn(10, 27, 112, 112).astype(np.float32)
    fp32_out = session_fp32.run(None, {session_fp32.get_inputs()[0].name: test_dummy})[0]
    fp32_norm = fp32_out / np.linalg.norm(fp32_out, axis=1, keepdims=True)
    int8_out = session_int8.run(None, {session_int8.get_inputs()[0].name: test_dummy})[0]
    int8_norm = int8_out / np.linalg.norm(int8_out, axis=1, keepdims=True)

    int8_cos_sim = np.mean(np.sum(fp32_norm * int8_norm, axis=1))
    print(f"INT8 Cosine Similarity vs FP32: {int8_cos_sim:.5f}")

    # Write log
    with open(log_file, "w") as f:
        f.write("=== ONNX Export and Benchmark Report ===\n")
        f.write(
            "Opset Version:           14 (Pinned for dynamic shapes and modern operator support)\n"
        )
        f.write("Input Name:              partial_frequency\n")
        f.write("Output Name:             embedding\n")
        f.write(f"FP32 Model Size:         {onnx_file_size_mb:.2f} MB\n")
        f.write(f"FP32 Max Abs Error:      {max_diff:.2e}\n")
        f.write(f"FP32 CPU Latency (BS=1): {b1_per_img:.2f} ms/image ({b1_fps:.1f} FPS)\n")
        f.write(f"FP32 CPU Latency (BS=32):{b32_per_img:.2f} ms/image ({b32_fps:.1f} FPS)\n")
        f.write("\n--- Dynamic INT8 Experiment ---\n")
        f.write(f"INT8 Model Size:         {quant_size_mb:.2f} MB\n")
        f.write(f"INT8 CPU Latency (BS=1): {q_b1_per_img:.2f} ms/image ({q_b1_fps:.1f} FPS)\n")
        f.write(f"INT8 CPU Latency (BS=32):{q_b32_per_img:.2f} ms/image ({q_b32_fps:.1f} FPS)\n")
        f.write(f"INT8 Mean Cosine vs FP32:{int8_cos_sim:.5f}\n")

    print(f"\n[SUCCESS] ONNX export and benchmark completed. Report saved to {log_file}")


if __name__ == "__main__":
    main()
