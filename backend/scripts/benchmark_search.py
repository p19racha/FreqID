#!/usr/bin/env python3
# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
benchmark_search.py: Benchmarks in-memory 1:N vector gallery search across varying scale factors.
"""

from __future__ import annotations

import time

import freqid_core as fq
import numpy as np


def run_benchmark():
    gallery_sizes = [100, 500, 1000, 5000, 10000, 50000]
    num_queries = 100
    dim = 512

    print("=" * 70)
    print("FreqID Server: 1:N Vector Search Scalability Benchmark")
    print(f"Embedding Dimension: {dim} | Query Iterations per Size: {num_queries}")
    print("=" * 70)
    print(
        f"{'Gallery Size':<15}{'Mean (ms)':<12}{'Median (ms)':<14}{'P95 (ms)':<12}{'Throughput (QPS)':<18}"
    )
    print("-" * 70)

    # Fixed seed for reproducibility
    rng = np.random.RandomState(42)

    for n in gallery_sizes:
        # Generate random normalized embeddings
        raw_gallery = rng.randn(n, dim).astype(np.float32)
        norms = np.linalg.norm(raw_gallery, axis=1, keepdims=True)
        gallery_embs = raw_gallery / norms
        gallery_ids = [f"user_{i:06d}" for i in range(n)]

        # Warmup
        warmup_query = rng.randn(dim).astype(np.float32)
        warmup_query /= np.linalg.norm(warmup_query)
        _ = fq.identify(warmup_query, gallery_embs, gallery_ids, top_k=5)

        # Benchmark queries
        latencies_ms = []
        for _ in range(num_queries):
            query = rng.randn(dim).astype(np.float32)
            query /= np.linalg.norm(query)

            t0 = time.perf_counter()
            _ = fq.identify(query, gallery_embs, gallery_ids, top_k=5, threshold=0.35)
            t1 = time.perf_counter()
            latencies_ms.append((t1 - t0) * 1000.0)

        latencies_ms.sort()
        mean_ms = float(np.mean(latencies_ms))
        median_ms = float(np.median(latencies_ms))
        p95_ms = float(np.percentile(latencies_ms, 95))
        qps = 1000.0 / mean_ms if mean_ms > 0 else float("inf")

        print(f"{n:<15}{mean_ms:<12.3f}{median_ms:<14.3f}{p95_ms:<12.3f}{qps:<18.1f}")

    print("=" * 70)


if __name__ == "__main__":
    run_benchmark()
