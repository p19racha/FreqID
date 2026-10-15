#!/usr/bin/env python3
# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
load_test.py: Concurrent load testing script for freqid-server verifying throughput and latency.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
import time

import httpx
import numpy as np

# Ensure backend/src is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import freqid_core as fq

from freqid_server.main import create_app


def create_mock_payload_bytes() -> bytes:
    """Generates a valid 27-channel synthetic PartialFacePayload."""
    # 27 channels of 112x112 partial frequency representation
    rng = np.random.RandomState(123)
    data = rng.randn(27, 112, 112).astype(np.float32)
    payload = fq.PartialFacePayload(data=data)
    return payload.to_bytes()


async def run_load_test(
    concurrency: int = 4,
    total_requests: int = 40,
    server_url: str | None = None,
) -> None:
    print("=" * 70)
    print("FreqID Server Load Test")
    print(f"Concurrency: {concurrency} | Total Requests: {total_requests}")
    print("=" * 70)

    payload_bytes = create_mock_payload_bytes()

    # If no URL given, spin up in-process ASGI application
    app = None
    transport = None
    base_url = server_url or "http://testserver"

    if server_url is None:
        app = create_app()
        app.state.inference.start()
        transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url=base_url, timeout=30.0) as client:
        # First enroll a test user so verify works
        enroll_headers = {
            "Content-Type": "application/vnd.freqid.payload",
            "X-Device-ID": "load-test-kiosk",
            "X-User-ID": "test_user_load",
            "Authorization": "Bearer dev_admin_token",
        }
        res = await client.post("/v1/enroll", headers=enroll_headers, content=payload_bytes)
        if res.status_code not in (200, 201):
            print(f"Enrollment failed during setup: {res.status_code} {res.text}")
            return
        print("Successfully enrolled identity 'test_user_load' for load test.")

        latencies_ms: list[float] = []
        status_codes: dict[int, int] = {}
        sem = asyncio.Semaphore(concurrency)

        async def worker(req_idx: int) -> None:
            nonce = secrets.token_hex(16)
            headers = {
                "Content-Type": "application/vnd.freqid.payload",
                "X-Device-ID": f"load-test-device-{req_idx % concurrency}",
                "X-Claimed-Identity": "test_user_load",
                "X-Nonce": nonce,
                "Authorization": "Bearer dev_verify_token",
            }
            async with sem:
                t0 = time.perf_counter()
                r = await client.post("/v1/verify", headers=headers, content=payload_bytes)
                t1 = time.perf_counter()
                elapsed = (t1 - t0) * 1000.0
                latencies_ms.append(elapsed)
                code = r.status_code
                status_codes[code] = status_codes.get(code, 0) + 1

        t_start = time.perf_counter()
        tasks = [worker(i) for i in range(total_requests)]
        await asyncio.gather(*tasks)
        t_total = time.perf_counter() - t_start

    if app is not None:
        app.state.inference.shutdown()

    latencies_ms.sort()
    mean_ms = float(np.mean(latencies_ms))
    median_ms = float(np.median(latencies_ms))
    p95_ms = float(np.percentile(latencies_ms, 95))
    p99_ms = float(np.percentile(latencies_ms, 99))
    qps = total_requests / t_total

    print("\nResults:")
    print(f"Total Duration:   {t_total:.2f} s")
    print(f"Throughput:       {qps:.2f} req/s")
    print(f"Status Breakdown: {status_codes}")
    print(f"Latency Min:      {min(latencies_ms):.2f} ms")
    print(f"Latency Mean:     {mean_ms:.2f} ms")
    print(f"Latency Median:   {median_ms:.2f} ms")
    print(f"Latency P95:      {p95_ms:.2f} ms")
    print(f"Latency P99:      {p99_ms:.2f} ms")
    print(f"Latency Max:      {max(latencies_ms):.2f} ms")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="FreqID Server Load Testing Tool")
    parser.add_argument("--concurrency", type=int, default=4, help="Concurrent workers")
    parser.add_argument("--requests", type=int, default=40, help="Total requests to dispatch")
    parser.add_argument("--url", type=str, default=None, help="Target server URL (default: in-process ASGI)")
    args = parser.parse_args()

    asyncio.run(
        run_load_test(
            concurrency=args.concurrency,
            total_requests=args.requests,
            server_url=args.url,
        )
    )


if __name__ == "__main__":
    main()
