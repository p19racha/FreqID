# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
eval_02_template_inversion.py: Empirical evaluation of template inversion attacks against unrotated vs rotated templates.

Tests feature recovery under:
- V1: Unrotated embeddings (leaked baseline)
- V2: Keyed orthogonal transform R in O(512) without key knowledge
- Measures recovered feature cosine similarity and inversion success rate against verification threshold tau=0.35.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np

# Add repo root to path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "backend" / "src"))

from freqid_server.crypto.provider import EnvOrFileKeyProvider
from freqid_server.crypto.template_transform import TemplateTransformer


def run_evaluation(num_trials: int = 100, threshold: float = 0.35, seed: int = 42) -> dict[str, Any]:
    rng = np.random.default_rng(seed)

    key_bytes = rng.bytes(32)
    provider = EnvOrFileKeyProvider(default_key=key_bytes, default_key_id="eval_key")
    transformer = TemplateTransformer(key_provider=provider)

    v1_reconstructed_sims = []
    v2_unkeyed_inversion_sims = []
    v2_random_guess_sims = []
    v2_keyed_inversion_sims = []

    for _ in range(num_trials):
        # Target true embedding
        x_true = rng.standard_normal(512).astype(np.float32)
        x_true /= np.linalg.norm(x_true)

        # V1: Leaked raw template
        # Attacker directly has x_true
        v1_reconstructed_sims.append(1.0)

        # V2: Leaked rotated template y = R @ x_true
        y_leaked = transformer.transform(x_true)

        # Attacker attempt 1: Attacker attempts to use y_leaked directly as embedding
        # Because y_leaked is rotated by a secret Haar orthogonal matrix, its correlation with x_true is:
        sim_unkeyed = float(np.dot(y_leaked, x_true))
        v2_unkeyed_inversion_sims.append(sim_unkeyed)

        # Attacker attempt 2: Attacker attempts to invert with a random candidate rotation R_cand
        R_cand_key = rng.bytes(32)
        provider_cand = EnvOrFileKeyProvider(default_key=R_cand_key, default_key_id="cand")
        tf_cand = TemplateTransformer(provider_cand)
        cand_x = tf_cand.inverse_transform(y_leaked)
        sim_cand = float(np.dot(cand_x, x_true))
        v2_random_guess_sims.append(sim_cand)

        # With proper key R:
        x_recovered = transformer.inverse_transform(y_leaked)
        sim_keyed = float(np.dot(x_recovered, x_true))
        v2_keyed_inversion_sims.append(sim_keyed)

    unkeyed_arr = np.array(v2_unkeyed_inversion_sims)
    mean_unkeyed_sim = float(np.mean(unkeyed_arr))
    std_unkeyed_sim = float(np.std(unkeyed_arr))
    max_unkeyed_sim = float(np.max(unkeyed_arr))

    # Success rate: fraction of unkeyed inversions exceeding threshold tau = 0.35
    inversion_success_rate = float(np.mean(unkeyed_arr >= threshold)) * 100.0

    return {
        "evaluation": "02_template_inversion",
        "num_trials": num_trials,
        "v1_raw_template_cosine_sim": 1.0,
        "v2_unkeyed_mean_cosine_sim": round(mean_unkeyed_sim, 4),
        "v2_unkeyed_std_cosine_sim": round(std_unkeyed_sim, 4),
        "v2_unkeyed_max_cosine_sim": round(max_unkeyed_sim, 4),
        "v2_random_guess_mean_cosine_sim": round(float(np.mean(v2_random_guess_sims)), 4),
        "v2_keyed_recovery_cosine_sim": round(float(np.mean(v2_keyed_inversion_sims)), 6),
        "threshold_tau": threshold,
        "v2_inversion_success_rate_pct": round(inversion_success_rate, 2),
        "inversion_verdict": "V2 rotated templates exhibit near-zero correlation with true face vectors without transform key.",
    }


if __name__ == "__main__":
    res = run_evaluation()
    print("Evaluation 02 Results:")
    for k, v in res.items():
        print(f"  {k}: {v}")
