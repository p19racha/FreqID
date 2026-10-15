# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_key_hierarchy.py: Tests for subkey derivation and Shamir Secret Sharing CLI operations.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import x25519

from freqid_server.crypto.provider import EnvOrFileKeyProvider


def test_subkey_derivation_deterministic():
    master_key = os.urandom(32)
    provider = EnvOrFileKeyProvider(default_key=master_key, default_key_id="test_v1")

    # Derivations must be deterministic
    tpl1 = provider.derive_purpose_key("template")
    tpl2 = provider.derive_purpose_key("template")
    assert tpl1 == tpl2
    assert len(tpl1) == 32

    # Different purposes must yield distinct subkeys
    tr1 = provider.derive_purpose_key("transform")
    aud1 = provider.derive_purpose_key("audit")
    tok1 = provider.derive_purpose_key("token")
    pay1 = provider.derive_purpose_key("payload")

    subkeys = {tpl1, tr1, aud1, tok1, pay1}
    assert len(subkeys) == 5, "Subkeys for distinct purposes collided!"


def test_payload_keypair_derivation():
    master_key = os.urandom(32)
    provider = EnvOrFileKeyProvider(default_key=master_key, default_key_id="test_v1")

    priv, pub_bytes = provider.get_payload_keypair()
    assert isinstance(priv, x25519.X25519PrivateKey)
    assert len(pub_bytes) == 32

    # Verify that ECDH works between this derived key and an ephemeral peer
    peer_priv = x25519.X25519PrivateKey.generate()
    peer_pub = peer_priv.public_key()

    ss1 = priv.exchange(peer_pub)
    ss2 = peer_priv.exchange(priv.public_key())
    assert ss1 == ss2


def test_key_hierarchy_dataclass():
    master_key = os.urandom(32)
    provider = EnvOrFileKeyProvider(default_key=master_key, default_key_id="hier_v1")
    h = provider.get_key_hierarchy()

    assert h.master_key_id == "hier_v1"
    assert len(h.template_key) == 32
    assert len(h.transform_key) == 32
    assert len(h.audit_key) == 32
    assert len(h.token_key) == 32
    assert len(h.payload_public_key_bytes) == 32


def test_cli_generate_split_combine(tmp_path: Path):
    key_file = tmp_path / "master.key"
    rec_file = tmp_path / "recovered.key"

    # 1. Generate key
    res_gen = subprocess.run(
        [sys.executable, "scripts/freqid_keys.py", "generate", "--out", str(key_file)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert key_file.is_file()
    assert key_file.stat().st_mode & 0o777 == 0o600

    original_b64 = key_file.read_text(encoding="utf-8").strip()

    # 2. Split into 3-of-5 shares
    res_split = subprocess.run(
        [
            sys.executable,
            "scripts/freqid_keys.py",
            "split",
            "-f",
            str(key_file),
            "-k",
            "3",
            "-n",
            "5",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    # Parse shares from output
    output_lines = res_split.stdout.splitlines()
    shares = []
    capture = False
    for line in output_lines:
        line_str = line.strip()
        if line_str.startswith("--- [SHARE"):
            capture = True
            continue
        if capture and line_str and not line_str.startswith("---") and not line_str.startswith("[!]"):
            shares.append(line_str)
            capture = False

    assert len(shares) == 5

    # 3. Combine with 3 shares (threshold met)
    res_comb = subprocess.run(
        [
            sys.executable,
            "scripts/freqid_keys.py",
            "combine",
            "--shares",
            shares[0],
            shares[2],
            shares[4],
            "--out",
            str(rec_file),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    recovered_b64 = rec_file.read_text(encoding="utf-8").strip()
    assert recovered_b64 == original_b64
    assert rec_file.stat().st_mode & 0o777 == 0o600

    # 4. Fail when only 2 shares provided (below threshold)
    res_fail = subprocess.run(
        [
            sys.executable,
            "scripts/freqid_keys.py",
            "combine",
            "--shares",
            shares[0],
            shares[1],
        ],
        capture_output=True,
        text=True,
    )
    assert res_fail.returncode != 0
