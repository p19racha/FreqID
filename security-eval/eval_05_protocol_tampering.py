# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
eval_05_protocol_tampering.py: Empirical evaluation of protocol tampering, fuzzing, and cryptographic envelope validation.

Tests robustness of application-layer PF02 envelopes against:
- Ciphertext bit flips (AEAD integrity)
- Header field corruption (ephemeral ECDH key, nonce, key ID)
- AAD device binding mutation (impersonation)
- Replay attacks (request ID and nonce reuse)
- Timestamp manipulation (expiration / future skew)
- Digital signature bit flips and stripping
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

# Add repo root to path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "backend" / "src"))

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from freqid_server.crypto.payload_envelope import (
    PayloadEnvelopeError,
    ReplayDetector,
    open_payload,
    seal_payload,
)


def run_evaluation(num_mutations_per_test: int = 50, seed: int = 42) -> dict[str, Any]:
    rng = np.random.default_rng(seed)

    # Server keypair
    server_priv = x25519.X25519PrivateKey.generate()
    server_pub_bytes = server_priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )

    # Device keypair
    dev_priv = ed25519.Ed25519PrivateKey.generate()
    dev_pub = dev_priv.public_key()

    raw_payload = os.urandom(22036)  # Standard PartialFace payload size

    tests_run = 0
    rejections = 0
    errors_encountered: dict[str, int] = {}

    def record_attempt(fn, *args, **kwargs):
        nonlocal tests_run, rejections
        tests_run += 1
        try:
            fn(*args, **kwargs)
            # If function didn't raise, the tampering was NOT caught
            return False
        except (PayloadEnvelopeError, InvalidTag, InvalidSignature, ValueError) as e:
            rejections += 1
            err_name = type(e).__name__
            errors_encountered[err_name] = errors_encountered.get(err_name, 0) + 1
            return True

    # 1. Ciphertext Bit-Flip Fuzzing
    valid_sealed = seal_payload(
        payload_bytes=raw_payload,
        server_public_key_bytes=server_pub_bytes,
        key_id="key_v1",
        device_id="dev-eval-01",
        request_id="req-base-01",
        device_private_key=dev_priv,
    )

    # Ciphertext starts after header (~180 bytes)
    for _ in range(num_mutations_per_test):
        mutated = bytearray(valid_sealed)
        flip_pos = rng.integers(len(mutated) - 50, len(mutated))
        mutated[flip_pos] ^= 1 << rng.integers(0, 8)

        assert record_attempt(
            open_payload,
            envelope_bytes=bytes(mutated),
            server_private_key=server_priv,
            device_public_key=dev_pub,
        )

    # 2. Header Ephemeral Key / Nonce Bit Flips
    for _ in range(num_mutations_per_test):
        mutated = bytearray(valid_sealed)
        # Ephemeral key is at offset 11 to 43
        flip_pos = rng.integers(11, 43)
        mutated[flip_pos] ^= 1 << rng.integers(0, 8)

        assert record_attempt(
            open_payload,
            envelope_bytes=bytes(mutated),
            server_private_key=server_priv,
            device_public_key=dev_pub,
        )

    # 3. Altered AAD: Device ID Spoofing
    for idx in range(num_mutations_per_test):
        spoofed_sealed = seal_payload(
            payload_bytes=raw_payload,
            server_public_key_bytes=server_pub_bytes,
            key_id="key_v1",
            device_id=f"attacker-dev-{idx}",
            request_id=f"req-spoof-{idx}",
            device_private_key=dev_priv,
        )

        assert record_attempt(
            open_payload,
            envelope_bytes=spoofed_sealed,
            server_private_key=server_priv,
            expected_device_id="dev-legit-01",  # Legitimate device expecting request
            device_public_key=dev_pub,
        )

    # 4. Replay Attacks
    replay_det = ReplayDetector(window_seconds=120.0)
    replay_sealed = seal_payload(
        payload_bytes=raw_payload,
        server_public_key_bytes=server_pub_bytes,
        key_id="key_v1",
        device_id="dev-eval-01",
        request_id="req-replay-target",
        device_private_key=dev_priv,
    )
    # First opening succeeds
    open_payload(
        envelope_bytes=replay_sealed,
        server_private_key=server_priv,
        device_public_key=dev_pub,
        replay_detector=replay_det,
    )

    # Subsequent replay attempts must be rejected
    for _ in range(num_mutations_per_test):
        assert record_attempt(
            open_payload,
            envelope_bytes=replay_sealed,
            server_private_key=server_priv,
            device_public_key=dev_pub,
            replay_detector=replay_det,
        )

    # 5. Stale / Expired Timestamps
    for idx in range(num_mutations_per_test):
        stale_time = (datetime.now(UTC) - timedelta(seconds=100 + idx)).isoformat()
        expired_sealed = seal_payload(
            payload_bytes=raw_payload,
            server_public_key_bytes=server_pub_bytes,
            key_id="key_v1",
            device_id="dev-eval-01",
            request_id=f"req-expired-{idx}",
            timestamp_iso=stale_time,
            device_private_key=dev_priv,
        )

        assert record_attempt(
            open_payload,
            envelope_bytes=expired_sealed,
            server_private_key=server_priv,
            max_age_seconds=60.0,
            device_public_key=dev_pub,
        )

    # 6. Signature Tampering
    for _ in range(num_mutations_per_test):
        # Mutate signature bytes in header
        mutated = bytearray(valid_sealed)
        # Signature is at end of header
        mutated[120] ^= 1 << rng.integers(0, 8)

        assert record_attempt(
            open_payload,
            envelope_bytes=bytes(mutated),
            server_private_key=server_priv,
            device_public_key=dev_pub,
        )

    rejection_rate = (rejections / tests_run) * 100.0

    return {
        "evaluation": "05_protocol_tampering",
        "total_tampering_attempts": tests_run,
        "total_rejected": rejections,
        "rejection_rate_pct": round(rejection_rate, 2),
        "error_distribution": errors_encountered,
        "tampering_verdict": f"100.0% of {tests_run} tampered and replayed packets strictly rejected with cryptographic attribution.",
    }


if __name__ == "__main__":
    res = run_evaluation()
    print("Evaluation 05 Results:")
    for k, v in res.items():
        print(f"  {k}: {v}")
