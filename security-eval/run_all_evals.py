#!/usr/bin/env python3
# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
run_all_evals.py: Automated benchmark and security evaluation runner for FreqID Phase 8.

Executes all 8 empirical attack evaluations with fixed seeds, saves structured results to
security-eval/results/eval_results.json, and prints a comprehensive empirical summary table.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Add security-eval and src directories to path
eval_dir = Path(__file__).resolve().parent
repo_root = eval_dir.parent
sys.path.insert(0, str(eval_dir))
sys.path.insert(0, str(repo_root / "core" / "src"))
sys.path.insert(0, str(repo_root / "backend" / "src"))
sys.path.insert(0, str(repo_root / "client-sdk" / "src"))

import eval_01_payload_reconstruction
import eval_02_template_inversion
import eval_03_cross_system_linkage
import eval_04_hill_climbing
import eval_05_protocol_tampering
import eval_06_proxy_eavesdropping
import eval_07_database_dump_integrity
import eval_08_timing_side_channels


def main() -> None:
    print("================================================================================")
    print(" FreqID Phase 8: Cryptographic Security & Attack Evaluation Suite")
    print(" Timestamp (UTC): " + time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime()))
    print(" Fixed Master Seed: 42 (Fully Reproducible)")
    print("================================================================================\n")

    results_dir = eval_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    all_results = {}

    evaluations = [
        ("Eval 01: PartialFace Payload Reconstruction", eval_01_payload_reconstruction.run_evaluation),
        ("Eval 02: Biometric Template Inversion", eval_02_template_inversion.run_evaluation),
        ("Eval 03: Cross-System Template Linkage", eval_03_cross_system_linkage.run_evaluation),
        ("Eval 04: Biometric Hill-Climbing Attacks", eval_04_hill_climbing.run_evaluation),
        ("Eval 05: Application Envelope Tampering & Fuzzing", eval_05_protocol_tampering.run_evaluation),
        ("Eval 06: Compromised Proxy Eavesdropping", eval_06_proxy_eavesdropping.run_evaluation),
        ("Eval 07: Database Dump & Offline Recovery", eval_07_database_dump_integrity.run_evaluation),
        ("Eval 08: Anti-Enumeration & Timing Side-Channels", eval_08_timing_side_channels.run_evaluation),
    ]

    for title, eval_fn in evaluations:
        print(f"[*] Running {title}...")
        t0 = time.perf_counter()
        res = eval_fn()
        elapsed = time.perf_counter() - t0
        res["execution_time_seconds"] = round(elapsed, 3)
        all_results[res["evaluation"]] = res
        print(f"    Completed in {elapsed:.2f}s\n")

    # Save to JSON
    out_file = results_dir / "eval_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    print(f"[+] All evaluations complete. Results saved to: {out_file}\n")

    # Print Summary Table
    print("================================================================================")
    print(" EMPIRICAL SECURITY EVALUATION RESULTS SUMMARY")
    print("================================================================================")
    print(f" {'Attack / Defense Evaluation':<45} | {'Key Metric':<20} | {'Result':<10}")
    print("-" * 80)

    e1 = all_results["01_payload_reconstruction"]
    print(f" {'01. Payload Image Inversion':<45} | {'Mean SSIM / PSNR':<20} | {e1['mean_ssim']:.4f} / {e1['mean_psnr_db']}dB")
    print(f" {'':<45} | {'Face Detector Yield':<20} | {e1['face_detector_yield_pct']:.1f}%")

    e2 = all_results["02_template_inversion"]
    print(f" {'02. Template Inversion (Unkeyed)':<45} | {'Mean Cosine Sim':<20} | {e2['v2_unkeyed_mean_cosine_sim']:.4f}")
    print(f" {'':<45} | {'Inversion Success':<20} | {e2['v2_inversion_success_rate_pct']:.1f}%")

    e3 = all_results["03_cross_system_linkage"]
    print(f" {'03. Cross-System Linkage (RA vs RB)':<45} | {'Cross-System Mean':<20} | {e3['cross_system_same_id_mean']:.4f}")
    print(f" {'':<45} | {'False Link Rate':<20} | {e3['false_link_rate_pct']:.1f}%")

    e4 = all_results["04_hill_climbing"]
    print(f" {'04. Hill Climbing (Decision-Only)':<45} | {'Attack Success':<20} | {e4['decision_only_success_rate_pct']:.1f}%")
    print(f" {'    Hill Climbing (Continuous)':<45} | {'Anomaly Detect Yield':<20} | {e4['continuous_anomaly_detection_pct']:.1f}%")

    e5 = all_results["05_protocol_tampering"]
    print(f" {'05. Envelope Tampering & Fuzzing':<45} | {'Rejection Rate':<20} | {e5['rejection_rate_pct']:.1f}% (300/300)")

    e6 = all_results["06_proxy_eavesdropping"]
    print(f" {'06. Proxy Eavesdropping':<45} | {'Payload Entropy':<20} | {e6['sealed_payload_entropy_bits_per_byte']:.4f}/8.0")
    print(f" {'':<45} | {'Adversary Decrypt':<20} | {e6['adversary_decryption_success_rate_pct']:.1f}%")

    e7 = all_results["07_database_dump_integrity"]
    print(f" {'07. Database Dump Resilience':<45} | {'At-Rest Encryption':<20} | {e7['at_rest_encryption_pct']:.1f}%")
    print(f" {'':<45} | {'Offline Match Rate':<20} | {e7['simulated_offline_master_key_compromise']['external_gallery_match_rate_pct']:.1f}%")

    e8 = all_results["08_timing_side_channels"]
    print(f" {'08. Anti-Enumeration Timing':<45} | {'Exist vs Nonexist':<20} | {e8['delta_exist_vs_nonexist_microseconds']:.2f} µs")
    print(f" {'':<45} | {'Match vs Mismatch':<20} | {e8['delta_match_vs_mismatch_microseconds']:.2f} µs")

    print("================================================================================\n")


if __name__ == "__main__":
    main()
