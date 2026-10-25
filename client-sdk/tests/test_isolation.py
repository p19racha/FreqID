# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_isolation.py: Automated proof that freqid_client runs without importing torch or onnxruntime.
"""

import subprocess
import sys


def test_client_does_not_import_torch_or_onnxruntime():
    """
    Spawns a pristine Python process and executes freqid_client modules.
    Asserts that neither torch nor onnxruntime is loaded into sys.modules.
    """
    code = """
import sys

# Import freqid_client and its components
import freqid_client
from freqid_client.config import ClientConfig
from freqid_client.detect import FaceDetection
from freqid_client.align import align_face
from freqid_client.quality import QualityGate
from freqid_client.camera import SingleImageSource
from freqid_client.auth import StaticTokenAuthenticator, NoAuth
from freqid_client.transport import FreqIDTransport
from freqid_client.pipeline import ClientPipeline

forbidden = ["torch", "onnxruntime", "torchvision", "torchjpeg"]
loaded_forbidden = [mod for mod in forbidden if mod in sys.modules]

if loaded_forbidden:
    print(f"FAILED: Found forbidden heavy neural network libraries loaded in client: {loaded_forbidden}")
    sys.exit(1)

print("PASSED")
sys.exit(0)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"Client isolation test failed:\nStdout: {result.stdout}\nStderr: {result.stderr}"
    )
    assert "PASSED" in result.stdout
