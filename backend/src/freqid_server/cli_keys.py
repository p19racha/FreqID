# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
cli_keys.py: Administrative CLI for master key generation, Shamir Secret Sharing backup, and rotation.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import os
import stat
import sys
from pathlib import Path

import shamir_mnemonic
from cryptography.hazmat.primitives import hashes

from freqid_server.crypto.provider import EnvOrFileKeyProvider


def cmd_generate(args: argparse.Namespace) -> None:
    key_bytes = os.urandom(32)
    b64_key = base64.b64encode(key_bytes).decode("ascii")
    hex_key = key_bytes.hex()

    if args.out:
        p = Path(args.out).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        # Create or write with strict 0600 permissions
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mode = stat.S_IRUSR | stat.S_IWUSR  # 0600
        fd = os.open(str(p), flags, mode)
        with open(fd, "w", encoding="utf-8") as f:
            f.write(b64_key + "\n")
        print(f"[*] Generated 256-bit master key saved to: {p} (permissions 0600)")
    else:
        print("[*] Generated 256-bit Master Key (AES-256 / HKDF root):")
        print(f"    Base64: {b64_key}")
        print(f"    Hex:    {hex_key}")
        print("\n[!] WARNING: Keep this key strictly confidential. Store in environment variable or 0600 file.")


def _read_master_key(args: argparse.Namespace) -> bytes:
    if args.key:
        try:
            return base64.b64decode(args.key)
        except (binascii.Error, ValueError):
            try:
                return bytes.fromhex(args.key)
            except ValueError as e:
                raise ValueError("Provided key is neither valid Base64 nor Hex.") from e
    elif args.key_file:
        p = Path(args.key_file).resolve()
        content = p.read_text(encoding="utf-8").strip()
        try:
            return base64.b64decode(content)
        except (binascii.Error, ValueError):
            return bytes.fromhex(content)
    else:
        raise ValueError("Must provide --key or --key-file.")


def cmd_split(args: argparse.Namespace) -> None:
    key_bytes = _read_master_key(args)
    if len(key_bytes) != 32:
        print(f"Error: Master key must be 32 bytes (got {len(key_bytes)})", file=sys.stderr)
        sys.exit(1)

    threshold = args.threshold
    shares = args.shares

    if threshold < 2:
        print("Error: Threshold (-k) must be at least 2", file=sys.stderr)
        sys.exit(1)
    if threshold > shares:
        print(f"Error: Threshold ({threshold}) cannot exceed total shares ({shares})", file=sys.stderr)
        sys.exit(1)

    # SLIP-0039 Shamir Secret Sharing
    groups = [(threshold, shares)]
    mnemonics = shamir_mnemonic.generate_mnemonics(
        group_threshold=1,
        groups=groups,
        master_secret=key_bytes,
    )

    share_list = mnemonics[0]

    digest = hashes.Hash(hashes.SHA256())
    digest.update(key_bytes)
    fingerprint = digest.finalize()[:8].hex()

    print("================================================================================")
    print(" FreqID Shamir Secret Sharing Backup (SLIP-0039 Standard)")
    print(f" Master Key Fingerprint (SHA-256[:8]): {fingerprint}")
    print(f" Scheme: {threshold}-of-{shares} threshold recovery")
    print("================================================================================")
    print("Each share below contains error detection and group parameters.")
    print("Distribute these shares to separate custodians or distinct physical locations.")
    print(f"Any {threshold} shares can fully reconstruct the master key.")
    print("--------------------------------------------------------------------------------\n")

    for i, share_words in enumerate(share_list, start=1):
        print(f"--- [SHARE {i}/{shares}] ---")
        print(share_words)
        print()

    print("--------------------------------------------------------------------------------")
    print("[!] IMPORTANT: Never store all shares together digitally or in unencrypted text.")


def cmd_combine(args: argparse.Namespace) -> None:
    shares = []
    if args.share_files:
        for sf in args.share_files:
            p = Path(sf).resolve()
            shares.append(p.read_text(encoding="utf-8").strip())
    elif args.shares:
        shares = args.shares
    else:
        print("Enter Shamir mnemonic shares one per line (end with an empty line or EOF):")
        while True:
            try:
                line = input().strip()
                if not line:
                    break
                shares.append(line)
            except EOFError:
                break

    if not shares:
        print("Error: No shares provided.", file=sys.stderr)
        sys.exit(1)

    try:
        recovered = shamir_mnemonic.combine_mnemonics(shares)
    except (shamir_mnemonic.MnemonicError, ValueError) as e:
        print(f"Error: Failed to reconstruct master key from provided shares: {e}", file=sys.stderr)
        sys.exit(1)

    digest = hashes.Hash(hashes.SHA256())
    digest.update(recovered)
    fingerprint = digest.finalize()[:8].hex()

    b64_key = base64.b64encode(recovered).decode("ascii")

    print("[*] Successfully reconstructed master key!")
    print(f"    Fingerprint (SHA-256[:8]): {fingerprint}")
    print(f"    Base64: {b64_key}")

    if args.out:
        p = Path(args.out).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mode = stat.S_IRUSR | stat.S_IWUSR  # 0600
        fd = os.open(str(p), flags, mode)
        with open(fd, "w", encoding="utf-8") as f:
            f.write(b64_key + "\n")
        print(f"[*] Reconstructed key written to: {p} (permissions 0600)")


def cmd_subkeys(args: argparse.Namespace) -> None:
    key_bytes = _read_master_key(args)
    provider = EnvOrFileKeyProvider(default_key=key_bytes, default_key_id="active_key")
    hierarchy = provider.get_key_hierarchy()

    print("Master Key Hierarchy Status:")
    print(f"  Active Key ID: {hierarchy.master_key_id}")

    for purpose in ["template", "transform", "audit", "token"]:
        sk = provider.derive_purpose_key(purpose)
        fp = hashes.Hash(hashes.SHA256())
        fp.update(sk)
        print(f"  Subkey '{purpose:9s}': SHA-256 fingerprint: {fp.finalize()[:8].hex()} (32 bytes)")

    _, pub_bytes = provider.get_payload_keypair()
    print(f"  Subkey 'payload'  : X25519 public key (hex): {pub_bytes.hex()}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="freqid-keys",
        description="FreqID Master Key & Shamir Secret Sharing Management Utility",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # generate
    p_gen = subparsers.add_parser("generate", help="Generate a fresh cryptographically random 256-bit master key")
    p_gen.add_argument("--out", "-o", help="Path to write master key file with 0600 permissions")

    # split
    p_split = subparsers.add_parser("split", help="Split master key into K-of-N Shamir secret shares (SLIP-0039)")
    p_split.add_argument("--key", help="Raw master key in Base64 or Hex")
    p_split.add_argument("--key-file", "-f", help="Path to master key file")
    p_split.add_argument("-k", "--threshold", type=int, default=3, help="Recovery threshold K (default: 3)")
    p_split.add_argument("-n", "--shares", type=int, default=5, help="Total number of shares N (default: 5)")

    # combine
    p_comb = subparsers.add_parser("combine", help="Combine K shares to reconstruct master key")
    p_comb.add_argument("--share-files", nargs="+", help="Files containing mnemonic shares")
    p_comb.add_argument("--shares", nargs="+", help="Share mnemonics passed directly")
    p_comb.add_argument("--out", "-o", help="Path to write reconstructed master key file (0600)")

    # subkeys
    p_sub = subparsers.add_parser("subkeys", help="Display derived HKDF subkey fingerprints")
    p_sub.add_argument("--key", help="Raw master key in Base64 or Hex")
    p_sub.add_argument("--key-file", "-f", help="Path to master key file")

    args = parser.parse_args()

    if args.subcommand == "generate":
        cmd_generate(args)
    elif args.subcommand == "split":
        cmd_split(args)
    elif args.subcommand == "combine":
        cmd_combine(args)
    elif args.subcommand == "subkeys":
        cmd_subkeys(args)


if __name__ == "__main__":
    main()
