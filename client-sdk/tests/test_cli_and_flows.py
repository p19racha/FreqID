# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_cli_and_flows.py: Tests covering CLI commands, authentication, camera sources, and enrollment flow.
"""

import argparse
import os
import stat

import numpy as np

from freqid_client.auth import (
    NoAuth,
    StaticTokenAuthenticator,
    load_device_credentials,
    save_device_credentials,
)
from freqid_client.camera import ImageFolderSource, SingleImageSource
from freqid_client.cli import cmd_check
from freqid_client.config import ClientConfig


def test_auth_token_and_file(tmp_path):
    token = "test_secret_token_abc123"
    auth = StaticTokenAuthenticator(token=token)
    headers = auth.get_auth_headers()
    assert headers["Authorization"] == f"Bearer {token}"

    token_file = tmp_path / "creds" / "device_auth.json"
    save_device_credentials({"device_id": "dev1", "token": token}, token_file)
    assert token_file.is_file()

    # Verify POSIX permissions 0600
    file_mode = stat.S_IMODE(os.stat(token_file).st_mode)
    assert file_mode == 0o600

    loaded = load_device_credentials(token_file)
    assert loaded["token"] == token
    assert loaded["device_id"] == "dev1"


def test_no_auth():
    auth = NoAuth()
    assert auth.get_auth_headers() == {}


def test_camera_sources(tmp_path):
    # Test SingleImageSource
    img = np.full((120, 120, 3), 100, dtype=np.uint8)
    cam_single = SingleImageSource(img)
    with cam_single:
        frame1 = cam_single.read_frame()
        assert frame1 is not None and frame1.shape == (120, 120, 3)
        frame2 = cam_single.read_frame()
        assert frame2 is None

    # Test ImageFolderSource
    import cv2

    img1_path = tmp_path / "img1.png"
    img2_path = tmp_path / "img2.png"
    cv2.imwrite(str(img1_path), img)
    cv2.imwrite(str(img2_path), img)

    cam_folder = ImageFolderSource(tmp_path)
    with cam_folder:
        assert len(cam_folder._files) == 2
        f1 = cam_folder.read_frame()
        assert f1 is not None
        f2 = cam_folder.read_frame()
        assert f2 is not None
        f3 = cam_folder.read_frame()
        assert f3 is None


def test_config_env_overrides(monkeypatch):
    monkeypatch.setenv("FREQID_SERVER_URL", "https://override.example.com")
    monkeypatch.setenv("FREQID_CAMERA_INDEX", "3")
    monkeypatch.setenv("FREQID_DEVICE_ID", "edge-device-99")

    cfg = ClientConfig.from_dict({})
    assert cfg.server_url == "https://override.example.com"
    assert cfg.camera_index == 3
    assert cfg.device_id == "edge-device-99"


def test_cli_check_command(capsys):
    cfg = ClientConfig(server_url="http://invalid-test-url:9999")
    args = argparse.Namespace()
    _ = cmd_check(args, cfg)
    # Check runs diagnostics and prints status
    captured = capsys.readouterr()
    assert "FreqID Edge Client Diagnostic Check" in captured.out
    assert "Configuration: Loaded" in captured.out
