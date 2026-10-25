# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
cli.py: Command line interface for freqid-client.

Commands:
- check: Health check verifying camera, detector, config, and server reachability.
- capture: Captures face, verifies quality, and writes binary PartialFacePayload to disk.
- verify: Live capture and 1:1 biometric verification against server.
- enroll: Guided multi-capture enrollment against server.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from freqid_client.auth import (
    NoAuth,
    StaticTokenAuthenticator,
    load_device_credentials,
    pair_device,
)
from freqid_client.camera import WebcamSource
from freqid_client.config import ClientConfig
from freqid_client.detect import YuNetFaceDetector
from freqid_client.enroll import EnrollmentCoordinator, EnrollmentProgress
from freqid_client.pipeline import ClientPipeline
from freqid_client.transport import FreqIDTransport


def cmd_check(args: argparse.Namespace, cfg: ClientConfig) -> int:
    print("=== FreqID Edge Client Diagnostic Check ===")
    all_ok = True

    # 1. Config check
    print(f"[*] Configuration: Loaded (Device ID: {cfg.device_id}, Server: {cfg.server_url})")

    # 2. Detector check
    try:
        _ = YuNetFaceDetector(model_path=cfg.detector_model_path)
        print(f"[PASS] Face Detector: Initialized successfully ({cfg.detector_model_path})")
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] Face Detector: Failed to initialize ({e})")
        all_ok = False

    # 3. Camera check
    try:
        cam = WebcamSource(
            camera_index=cfg.camera_index, width=cfg.camera_width, height=cfg.camera_height
        )
        cam.open()
        frame = cam.read_frame()
        cam.release()
        if frame is not None:
            print(
                f"[PASS] Camera: Accessible (Index {cfg.camera_index}, Frame shape {frame.shape})"
            )
        else:
            print(f"[WARN] Camera: Opened but returned empty frame (Index {cfg.camera_index})")
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] Camera: Not accessible at index {cfg.camera_index} ({e})")

    # 4. Server reachability check
    try:
        r = httpx.get(f"{cfg.server_url}/health", timeout=3.0)
        if r.status_code == 200:
            print(
                f"[PASS] Server Connectivity: Reachable ({cfg.server_url} - HTTP {r.status_code})"
            )
        else:
            print(f"[WARN] Server Connectivity: Returned status HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] Server Connectivity: Cannot reach {cfg.server_url} ({e})")

    print("\nResult:", "ALL SYSTEMS OPERATIONAL" if all_ok else "DIAGNOSTIC ISSUES DETECTED")
    return 0 if all_ok else 1


def cmd_capture(args: argparse.Namespace, cfg: ClientConfig) -> int:
    pipeline = ClientPipeline(config=cfg)
    cam = WebcamSource(
        camera_index=cfg.camera_index, width=cfg.camera_width, height=cfg.camera_height
    )

    print("[*] Opening camera to capture single face payload...")
    with cam:
        result = pipeline.capture_best_frame(cam, window_frames=5)

    if not result.success:
        print(f"[FAIL] Capture rejected: {result.rejection_reason}")
        print(f"       Details: {result.quality_report.failure_message}")
        return 1

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(result.payload_bytes)  # type: ignore[arg-type]

    print("[SUCCESS] Face captured and converted to partial frequency representation.")
    print(f"          Payload written to: {out_path} ({result.payload_size_bytes} bytes)")
    print("          [PRIVACY] Raw image destroyed immediately; only protected payload saved.")
    return 0


def cmd_verify(args: argparse.Namespace, cfg: ClientConfig) -> int:
    pipeline = ClientPipeline(config=cfg)
    auth = StaticTokenAuthenticator(cfg.auth_token) if cfg.auth_token else NoAuth()
    transport = FreqIDTransport(
        server_url=cfg.server_url,
        device_id=cfg.device_id,
        auth=auth,
        ca_cert_path=cfg.ca_cert_path,
        insecure_skip_verify=cfg.insecure_skip_verify,
    )
    cam = WebcamSource(
        camera_index=cfg.camera_index, width=cfg.camera_width, height=cfg.camera_height
    )

    print(f"[*] Capturing frame for verification against user '{args.user_id}'...")
    with cam:
        result = pipeline.capture_best_frame(cam, window_frames=5)

    if not result.success:
        print(f"[FAIL] Capture rejected by quality gate: {result.rejection_reason}")
        print(f"       Details: {result.quality_report.failure_message}")
        return 1

    print(f"[*] Transmitting partial frequency payload ({result.payload_size_bytes} bytes)...")
    res = transport.verify(
        payload_bytes=result.payload_bytes,  # type: ignore[arg-type]
        claimed_identity=args.user_id,
    )

    is_match = res.get("is_match", False)
    sim = res.get("similarity", 0.0)
    thresh = res.get("threshold", 0.35)

    print("\n=== Verification Result ===")
    print(f"Claimed Identity: {args.user_id}")
    print(f"Cosine Score:     {sim:.4f} (Threshold: {thresh:.4f})")
    print(
        f"Decision:         {'VERIFIED (Access Granted)' if is_match else 'REJECTED (Access Denied)'}"
    )
    return 0 if is_match else 1


def cmd_enroll(args: argparse.Namespace, cfg: ClientConfig) -> int:
    pipeline = ClientPipeline(config=cfg)
    coordinator = EnrollmentCoordinator(pipeline=pipeline, target_frames=args.frames)
    auth = StaticTokenAuthenticator(cfg.auth_token) if cfg.auth_token else NoAuth()
    transport = FreqIDTransport(
        server_url=cfg.server_url,
        device_id=cfg.device_id,
        auth=auth,
        ca_cert_path=cfg.ca_cert_path,
        insecure_skip_verify=cfg.insecure_skip_verify,
    )
    cam = WebcamSource(
        camera_index=cfg.camera_index, width=cfg.camera_width, height=cfg.camera_height
    )

    def _on_progress(p: EnrollmentProgress) -> None:
        print(f"[{p.status}] ({p.frames_captured}/{p.target_frames}): {p.prompt_message}")

    print(f"=== Starting Guided Enrollment for User '{args.user_id}' ===")
    with cam:
        payloads = coordinator.enroll(cam, progress_callback=_on_progress)

    print(f"\n[*] Submitting {len(payloads)} enrollment frames to {cfg.server_url}...")
    res = transport.enroll(payload_bytes_list=payloads, user_id=args.user_id)
    print(
        f"[SUCCESS] User '{args.user_id}' successfully enrolled (Template ID: {res.get('template_id')})"
    )
    return 0


def cmd_pair(args: argparse.Namespace, cfg: ClientConfig) -> int:
    print("=== Pairing Edge Device with FreqID Server ===")
    print(f"[*] Target Server: {args.server}")
    print(f"[*] Device Name:   {args.name}")

    try:
        result = pair_device(
            server_url=args.server,
            token=args.token,
            name=args.name,
            credentials_path=args.credentials,
            insecure_skip_verify=args.insecure_skip_verify,
            ca_cert_path=args.ca_cert,
        )
    except Exception as e:
        print(f"[FAIL] Pairing failed: {e}", file=sys.stderr)
        return 1

    print("[SUCCESS] Device successfully paired with server.")
    print(f"          Device ID: {result['device_id']}")
    print(f"          Status:    {result['state']}")
    print(f"          Key ID:    {result['key_id']}")
    print(f"          Credentials stored at: {result['credentials_path']} (POSIX 0600)")
    print("          [PRIVACY] Private key stored locally; zero keys or tokens logged.")
    return 0


def cmd_status(args: argparse.Namespace, cfg: ClientConfig) -> int:
    print("=== FreqID Edge Device Status ===")
    creds_path = Path(args.credentials).expanduser().resolve()
    if not creds_path.is_file():
        print(f"[FAIL] Device is not paired. Credentials file not found: {creds_path}")
        return 1

    try:
        creds = load_device_credentials(creds_path)
    except Exception as e:
        print(f"[FAIL] Cannot load credentials: {e}")
        return 1

    print(f"[*] Device ID:     {creds.get('device_id')}")
    print(f"[*] Device Name:   {creds.get('device_name')}")
    print(f"[*] Server URL:    {creds.get('server_url')}")
    print(f"[*] Key ID:        {creds.get('key_id')}")
    print(f"[*] Credentials:   {creds_path} (Owner-only permissions verified)")

    # Check server reachability
    server_url = creds.get("server_url", cfg.server_url)
    try:
        r = httpx.get(f"{server_url}/healthz", timeout=3.0)
        if r.status_code == 200:
            print(f"[PASS] Server Connectivity: Reachable ({server_url})")
        else:
            print(f"[WARN] Server Connectivity: HTTP {r.status_code}")
    except Exception as e:
        print(f"[WARN] Server Connectivity: Cannot reach server ({e})")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="FreqID Privacy-Preserving Edge Client SDK CLI")
    parser.add_argument("--config", "-c", default=None, help="Path to config YAML file")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # check
    subparsers.add_parser("check", help="Run device and connectivity diagnostics")

    # pair
    p_pair = subparsers.add_parser("pair", help="Pair device with server using single-use token")
    p_pair.add_argument(
        "--server", "-s", required=True, help="FreqID server URL (e.g. https://server:8000)"
    )
    p_pair.add_argument("--token", "-t", required=True, help="Single-use pairing token")
    p_pair.add_argument("--name", "-n", default="Edge Camera", help="Device name")
    p_pair.add_argument(
        "--credentials",
        default="~/.freqid/device_credentials.json",
        help="Path to credentials file",
    )
    p_pair.add_argument(
        "--insecure-skip-verify", action="store_true", help="Skip TLS verification (dev only)"
    )
    p_pair.add_argument("--ca-cert", default=None, help="Path to CA certificate")

    # status
    p_stat = subparsers.add_parser("status", help="Show device pairing state and reachability")
    p_stat.add_argument(
        "--credentials",
        default="~/.freqid/device_credentials.json",
        help="Path to credentials file",
    )

    # capture
    p_cap = subparsers.add_parser("capture", help="Capture single face and write payload to file")
    p_cap.add_argument("--out", "-o", default="payload.bin", help="Output payload file path")

    # verify
    p_ver = subparsers.add_parser("verify", help="Capture face and verify against server")
    p_ver.add_argument("--user-id", "-u", required=True, help="Claimed identity to verify")

    # enroll
    p_enr = subparsers.add_parser("enroll", help="Guided multi-capture enrollment")
    p_enr.add_argument("--user-id", "-u", required=True, help="User ID to enroll")
    p_enr.add_argument(
        "--frames", "-f", type=int, default=5, help="Number of frames to capture (default: 5)"
    )

    args = parser.parse_args()

    # Load configuration
    if args.config:
        cfg = ClientConfig.from_yaml(args.config)
    else:
        cfg = ClientConfig.from_dict({})

    if args.command == "check":
        sys.exit(cmd_check(args, cfg))
    elif args.command == "pair":
        sys.exit(cmd_pair(args, cfg))
    elif args.command == "status":
        sys.exit(cmd_status(args, cfg))
    elif args.command == "capture":
        sys.exit(cmd_capture(args, cfg))
    elif args.command == "verify":
        sys.exit(cmd_verify(args, cfg))
    elif args.command == "enroll":
        sys.exit(cmd_enroll(args, cfg))


if __name__ == "__main__":
    main()
