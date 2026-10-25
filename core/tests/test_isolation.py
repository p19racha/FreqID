# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
test_isolation.py: Automated proof that server-side modules never import raw image transforms.
"""

import subprocess
import sys


def test_server_modules_do_not_import_raw_image_transform():
    """
    Spawns a clean Python subprocess and imports server-side modules.
    Asserts that neither freqid_core.transform nor image libraries (cv2, PIL, torchjpeg)
    are present in sys.modules.
    """
    code = """
import sys

# Import server-side modules
from freqid_core.embedder import Embedder
from freqid_core.matching import verify, identify
from freqid_core.payload import PartialFacePayload

forbidden = ["freqid_core.transform", "cv2", "PIL", "torchjpeg"]
loaded_forbidden = [mod for mod in forbidden if mod in sys.modules]

if loaded_forbidden:
    print(f"FAILED: Found forbidden raw image modules loaded in server environment: {loaded_forbidden}")
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
        f"Isolation test failed:\nStdout: {result.stdout}\nStderr: {result.stderr}"
    )
    assert "PASSED" in result.stdout
