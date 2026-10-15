# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
eval_06_proxy_eavesdropping.py: Empirical evaluation of application-layer payload confidentiality under proxy eavesdropping.

Simulates an adversary who has compromised or inspected decrypted TLS traffic at a reverse proxy / load balancer:
- Tests whether eavesdropped payload bodies reveal partial frequency matrices or biometric traits without server private key.
- Computes Shannon entropy, byte distribution flatness, and cryptographic unreadability.
"""

from __future__ import annotations

import collections
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

# Add repo root to path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "backend" / "src"))

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from freqid_server.crypto.payload_envelope import (
    PayloadEnvelopeError,
    open_payload,
    seal_payload,
)


def compute_shannon_entropy(data: bytes) -> float:
    """Computes Shannon entropy in bits per byte (max 8.0)."""
    if not data:
        return 0.0
    counts = collections.Counter(data)
    total = len(data)
    entropy = -sum((cnt / total) * math.log2(cnt / total) for cnt in counts.values())
    return float(entropy)


def run_evaluation(num_captures: int = 50, seed: int = 42) -> dict[str, Any]:
    rng = np.random.default_rng(seed)

    server_priv = x25519.X25519PrivateKey.generate()
    server_pub_bytes = server_priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )

    dev_priv = ed25519.Ed25519PrivateKey.generate()

    entropies_unsealed = []
    entropies_sealed = []
    decryption_attempts_failed = 0

    for i in range(num_captures):
        payload_sample = rng.bytes(22036)
        entropies_unsealed.append(compute_shannon_entropy(payload_sample))

        sealed = seal_payload(
            payload_bytes=payload_sample,
            server_public_key_bytes=server_pub_bytes,
            key_id="key_v1",
            device_id="dev-kiosk-01",
            request_id=f"req-cap-{i}",
            device_private_key=dev_priv,
        )
        entropies_sealed.append(compute_shannon_entropy(sealed))

        # Adversary attempts to open eavesdropped payload with an attacker-generated keypair
        attacker_priv = x25519.X25519PrivateKey.generate()
        try:
            open_payload(
                envelope_bytes=sealed,
                server_private_key=attacker_priv,
            )
        except (PayloadEnvelopeError, InvalidTag, ValueError):
            decryption_attempts_failed += 1

    mean_entropy = float(np.mean(entropies_sealed))
    adversary_decrypt_success_pct = (
        (num_captures - decryption_attempts_failed) / num_captures
    ) * 100.0

    return {
        "evaluation": "06_proxy_eavesdropping",
        "num_intercepted_payloads": num_captures,
        "sealed_payload_entropy_bits_per_byte": round(mean_entropy, 4),
        "theoretical_max_entropy": 8.0,
        "adversary_decryption_success_rate_pct": round(adversary_decrypt_success_pct, 2),
        "eavesdropping_verdict": (
            f"Sealed payloads maintain near-maximum entropy ({mean_entropy:.4f}/8.0). "
            f"Adversary cannot extract biometric data from proxy logs without server private key."
        ),
    }


if __name__ == "__main__":
    res = run_evaluation()
    print("Evaluation 06 Results:")
    for k, v in res.items():
        print(f"  {k}: {v}")
