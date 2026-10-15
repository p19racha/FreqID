# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_isolation.py: Enforces strict privacy isolation boundaries (Hard Rule 2).

Proves that freqid-server NEVER imports raw-image transform or spatial image libraries:
- Prohibited: cv2, PIL, PIL.Image, torchvision, freqid_core.transform
- Permitted: freqid_core.payload, freqid_core.embedder, freqid_core.matching
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_static_code_isolation():
    """Verifies that no source code in backend/ imports prohibited image modules."""
    backend_src = Path(__file__).resolve().parent.parent / "src" / "freqid_server"
    prohibited_tokens = [
        "import cv2",
        "from cv2",
        "import PIL",
        "from PIL",
        "freqid_core.transform",
        "import torchvision",
        "from torchvision",
    ]

    for py_file in backend_src.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for token in prohibited_tokens:
            assert token not in content, (
                f"Isolation violation in {py_file.name}: contains forbidden token '{token}'"
            )


def test_runtime_isolation():
    """Runs a fresh Python subprocess to prove that importing freqid-server does not load prohibited modules."""
    script = """
import sys

# Import the server application
import freqid_server
from freqid_server.main import create_app

prohibited = ["cv2", "PIL", "PIL.Image", "freqid_core.transform", "torchvision"]
loaded_prohibited = [mod for mod in prohibited if mod in sys.modules]

if loaded_prohibited:
    print(f"FAILED: Prohibited modules loaded into sys.modules: {loaded_prohibited}", file=sys.stderr)
    sys.exit(1)

print("SUCCESS: Zero prohibited image libraries in sys.modules.")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"Runtime isolation check failed:\n{result.stderr}"
    assert "SUCCESS: Zero prohibited image libraries in sys.modules." in result.stdout
