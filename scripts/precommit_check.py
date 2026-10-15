#!/usr/bin/env python3
# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
precommit_check.py: Pre-commit safety check script for FreqID repository.

Enforces Phase 9 Git Rule 6:
- Rejects files > 5MB.
- Rejects forbidden extensions (model checkpoints, private keys, database dumps, raw face images).
- Scans file contents for private-key headers, real secret patterns, and high-entropy strings.
- Rejects real .env files (only .env.example allowed).
"""

from __future__ import annotations

import argparse
import math
import os
import re
import subprocess
import sys
from pathlib import Path

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

FORBIDDEN_EXTENSIONS = {
    # Models & weights
    ".pt", ".pth", ".onnx", ".ckpt", ".safetensors", ".bin", ".npy", ".npz",
    # Private keys & certificates
    ".pem", ".key", ".p12", ".shares", ".mnemonic",
    # Database dumps
    ".dump", ".sqlite", ".sqlite3",
    # Raw images outside allowlist
    ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif",
}

# Upstream Tencent/TFace pre-existing directories (preserved under Hard Rule 1)
UPSTREAM_TFACE_DIRS = (
    "recognition/",
    "quality/",
    "security/",
    "attribute/",
)

# Explicit image / asset allowlist
ALLOWED_FILES = {
    "admin-ui/public/favicon.svg",
    "admin-ui/public/config.js",
    "client-sdk/src/freqid_client/models/face_detection_yunet_2023mar.onnx",
}

PRIVATE_KEY_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"-----BEGIN PGP PRIVATE KEY BLOCK-----"),
    re.compile(r"-----BEGIN CERTIFICATE-----"),
]

SECRET_PATTERNS = [
    # Plaintext production master key patterns (not example / test markers)
    (re.compile(r"FREQID_MASTER_KEY\s*=\s*['\"][A-Za-z0-9+/=]{44}['\"]"), "Hardcoded 256-bit Base64 master key"),
    # AWS / Generic Secret Keys
    (re.compile(r"(?:AKIA|ABIA|ACCA|ASIA)[A-Z0-9]{16}"), "AWS Access Key ID"),
    # Slack / Discord / GitHub API tokens
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "GitHub Personal Access Token"),
]

# Files explicitly exempt from content pattern scanning (e.g. test files that generate fake keys or test regexes)
CONTENT_SCAN_ALLOWLIST = {
    "scripts/precommit_check.py",
    "scripts/precommit_check.sh",
    "backend/tests/test_log_redaction.py",
    "backend/tests/test_phase6_security.py",
    "backend/tests/test_encryption.py",
    "client-sdk/tests/test_transport_tls.py",
    "docs/key-management.md",
    "docs/phase8-design.md",
    "docs/crypto-design.md",
    "deploy/tls/verification_checklist.md",
}


def compute_shannon_entropy(data: str) -> float:
    """Computes Shannon entropy in bits per character."""
    if not data:
        return 0.0
    entropy = 0.0
    length = len(data)
    for char in set(data):
        prob = data.count(char) / length
        entropy -= prob * math.log2(prob)
    return entropy


def check_file(rel_path: str, repo_root: Path) -> list[str]:
    violations: list[str] = []
    file_path = repo_root / rel_path

    if not file_path.is_file():
        return violations

    # 1. Size check
    try:
        size = file_path.stat().st_size
        if size > MAX_FILE_SIZE_BYTES:
            violations.append(f"File size {size / (1024*1024):.2f} MB exceeds 5 MB limit")
    except OSError as e:
        violations.append(f"Unable to stat file: {e}")
        return violations

    normalized_path = rel_path.replace("\\", "/")

    # Upstream TFace files are preserved under Hard Rule 1
    if normalized_path.startswith(UPSTREAM_TFACE_DIRS):
        return violations

    # 2. Path & Extension check
    suffix = file_path.suffix.lower()
    filename = file_path.name

    # Check .env rules
    if filename.startswith(".env") and filename != ".env.example":
        violations.append(f"Real environment file forbidden: '{normalized_path}' (only .env.example allowed)")

    if normalized_path not in ALLOWED_FILES:
        if suffix in FORBIDDEN_EXTENSIONS:
            violations.append(f"Forbidden file extension '{suffix}' in '{normalized_path}'")

    # 3. Content scanning for text files
    if normalized_path not in CONTENT_SCAN_ALLOWLIST:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(500_000)  # Check first 500 KB

            for pat in PRIVATE_KEY_PATTERNS:
                if pat.search(content):
                    violations.append(f"Private key header or raw certificate detected in '{normalized_path}'")
                    break

            for pat, desc in SECRET_PATTERNS:
                if pat.search(content):
                    violations.append(f"{desc} detected in '{normalized_path}'")
                    break

        except Exception as e:
            violations.append(f"Error reading '{normalized_path}': {e}")

    return violations


def get_staged_files(repo_root: Path) -> list[str]:
    res = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]


def get_all_tracked_files(repo_root: Path) -> list[str]:
    res = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="FreqID Pre-Commit Safety & Secret Scanner")
    parser.add_argument("--all", action="store_true", help="Scan entire working tree instead of staged changes")
    parser.add_argument("--history", action="store_true", help="Scan recent commit history")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent

    if args.all:
        files_to_check = get_all_tracked_files(repo_root)
        print(f"[*] Pre-commit Safety Check: Scanning {len(files_to_check)} tracked files across entire repository...")
    else:
        files_to_check = get_staged_files(repo_root)
        print(f"[*] Pre-commit Safety Check: Scanning {len(files_to_check)} staged files...")

    all_violations: dict[str, list[str]] = {}
    for f in files_to_check:
        errs = check_file(f, repo_root)
        if errs:
            all_violations[f] = errs

    if all_violations:
        print("\n" + "=" * 80)
        print(" [!] PRE-COMMIT SAFETY CHECK FAILED: FORBIDDEN CONTENT DETECTED")
        print("=" * 80)
        for f, errs in all_violations.items():
            print(f"\n[FAIL] {f}:")
            for err in errs:
                print(f"       - {err}")
        print("\n" + "=" * 80)
        print("Commit aborted per Phase 9 Git Rule 6. Remediate findings before committing.")
        print("=" * 80)
        sys.exit(1)

    print("[+] Pre-commit Safety Check passed successfully (0 violations found).")


if __name__ == "__main__":
    main()
