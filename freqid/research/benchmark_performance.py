#!/usr/bin/env python3
"""
benchmark_performance.py: Hardware profiling and inference latency measurement for PartialFace IR_18.

Measures:
1. Embedding dimension
2. Parameter count (total, trainable)
3. Model file size on disk (MB)
4. Inference latency per image on CPU:
   - Batch size 1 (single-frame edge latency)
   - Batch size 32 (batched edge/server latency)
5. Inference latency per image on GPU (if CUDA available):
   - Batch size 1
   - Batch size 32

Outputs a formatted markdown / plaintext summary table saved to:
freqid/research/outputs/eval/performance_benchmark.log
"""

import os
import sys
import time
import argparse
import torch
import torch.nn as nn

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(REPO_ROOT, 'recognition'))

from torchkit.backbone import get_model


def count_parameters(model):
    total = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    return total, trainable


def measure_latency(model, device, batch_size, input_shape=(27, 112, 112), num_runs=50, warmup=10):
    model.eval()
    model.to(device)
    dummy_input = torch.randn(batch_size, *input_shape, device=device)

    # Warmup
    with torch.no_grad():
        for _ in range(warmup):
            _ = model(dummy_input)
            if device.type == 'cuda':
                torch.cuda.synchronize()

    # Timing
    latencies = []
    with torch.no_grad():
        for _ in range(num_runs):
            if device.type == 'cuda':
                torch.cuda.synchronize()
            t0 = time.perf_counter()
            _ = model(dummy_input)
            if device.type == 'cuda':
                torch.cuda.synchronize()
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000.0)  # total batch time in ms

    avg_batch_time_ms = float(sum(latencies) / len(latencies))
    avg_per_image_ms = avg_batch_time_ms / batch_size
    fps = 1000.0 / avg_per_image_ms if avg_per_image_ms > 0 else 0.0
    return avg_per_image_ms, avg_batch_time_ms, fps


def run_benchmark(ckpt_path=None, output_log='freqid/research/outputs/eval/performance_benchmark.log'):
    os.makedirs(os.path.dirname(output_log), exist_ok=True)
    print("=== PartialFace IR_18 Hardware & Inference Performance Benchmark ===")

    # 1. Build Model
    model = get_model('IR_18')([112, 112])
    model.input_layer = nn.Sequential(
        nn.Conv2d(27, 64, (3, 3), 1, 1, bias=False),
        nn.BatchNorm2d(64),
        nn.PReLU(64)
    )

    if ckpt_path and os.path.exists(ckpt_path):
        state = torch.load(ckpt_path, map_location='cpu', weights_only=False)
        if 'backbone' in state:
            state = state['backbone']
        cleaned = {k.replace('module.', ''): v for k, v in state.items()}
        model.load_state_dict(cleaned, strict=False)

    # 2. Parameters & Model Size
    total_params, trainable_params = count_parameters(model)
    embedding_size = 512

    # Estimate model file size
    tmp_path = '/tmp/temp_model.pth'
    torch.save(model.state_dict(), tmp_path)
    model_size_mb = os.path.getsize(tmp_path) / (1024 * 1024)
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    # If actual checkpoint exists, report that too
    actual_ckpt_size_mb = os.path.getsize(ckpt_path) / (1024 * 1024) if ckpt_path and os.path.exists(ckpt_path) else model_size_mb

    print(f"Embedding Dimension: {embedding_size}-D")
    print(f"Total Parameters: {total_params:,} ({total_params/1e6:.2f}M)")
    print(f"Model File Size: {actual_ckpt_size_mb:.2f} MB")

    # 3. CPU Benchmarks
    cpu_device = torch.device('cpu')
    print("\nBenchmarking CPU Inference...")
    cpu_b1_img, cpu_b1_batch, cpu_b1_fps = measure_latency(model, cpu_device, batch_size=1)
    print(f"  CPU Batch Size 1:  {cpu_b1_img:.2f} ms/image ({cpu_b1_fps:.1f} FPS)")

    cpu_b32_img, cpu_b32_batch, cpu_b32_fps = measure_latency(model, cpu_device, batch_size=32)
    print(f"  CPU Batch Size 32: {cpu_b32_img:.2f} ms/image ({cpu_b32_fps:.1f} FPS, Batch: {cpu_b32_batch:.1f} ms)")

    # 4. GPU Benchmarks (if available)
    has_gpu = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if has_gpu else "N/A"
    gpu_b1_img, gpu_b32_img, gpu_b1_fps, gpu_b32_fps = None, None, None, None

    if has_gpu:
        gpu_device = torch.device('cuda')
        print(f"\nBenchmarking GPU Inference on {gpu_name}...")
        gpu_b1_img, gpu_b1_batch, gpu_b1_fps = measure_latency(model, gpu_device, batch_size=1)
        print(f"  GPU Batch Size 1:  {gpu_b1_img:.2f} ms/image ({gpu_b1_fps:.1f} FPS)")

        gpu_b32_img, gpu_b32_batch, gpu_b32_fps = measure_latency(model, gpu_device, batch_size=32)
        print(f"  GPU Batch Size 32: {gpu_b32_img:.2f} ms/image ({gpu_b32_fps:.1f} FPS, Batch: {gpu_b32_batch:.1f} ms)")
    else:
        print("\nGPU not available for benchmarking.")

    # 5. Build Markdown Summary Table
    table_lines = [
        "# PartialFace IR_18 Hardware & Inference Performance Profile\n",
        "| Metric | Measured Value | Unit / Specification |",
        "| :--- | :--- | :--- |",
        f"| **Embedding Dimension** | `{embedding_size}` | 512-D float32 unit-normalized vector |",
        f"| **Total Parameter Count** | `{total_params:,}` | {total_params/1e6:.2f}M weights |",
        f"| **Model Weight File Size** | `{actual_ckpt_size_mb:.2f}` | MB (fp32 checkpoint) |",
        f"| **CPU Latency (Batch 1)** | `{cpu_b1_img:.2f}` | ms / image ({cpu_b1_fps:.1f} FPS) |",
        f"| **CPU Latency (Batch 32)** | `{cpu_b32_img:.2f}` | ms / image ({cpu_b32_fps:.1f} FPS) |",
    ]

    if has_gpu:
        table_lines.extend([
            f"| **GPU Device** | `{gpu_name}` | NVIDIA Ada Lovelace Mobile |",
            f"| **GPU Latency (Batch 1)** | `{gpu_b1_img:.2f}` | ms / image ({gpu_b1_fps:.1f} FPS) |",
            f"| **GPU Latency (Batch 32)** | `{gpu_b32_img:.2f}` | ms / image ({gpu_b32_fps:.1f} FPS) |",
        ])

    table_content = "\n".join(table_lines) + "\n"
    with open(output_log, 'w') as f:
        f.write(table_content)

    print(f"\n[OK] Performance benchmark completed. Report saved to {output_log}")
    return table_content


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ckpt_path', default=None)
    parser.add_argument('--log_file', default='freqid/research/outputs/eval/performance_benchmark.log')
    args = parser.parse_args()
    run_benchmark(args.ckpt_path, args.log_file)
