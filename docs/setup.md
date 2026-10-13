# FreqID: Environment Setup Guide

This guide documents the exact environment details and reproducible setup commands verified on this system during Phase 0.

## 1. System Hardware & Host Configuration

- **Operating System**: Linux x86_64
- **Host Python**: Python 3.12.3
- **Host Pip**: pip 24.0
- **GPU**: NVIDIA GeForce RTX 4070 Laptop GPU (8188 MiB VRAM)
- **NVIDIA Driver**: 581.80
- **CUDA Version**: 13.0

---

## 2. Dependency Analysis & Compatibility Challenges

The upstream `recognition/tasks/partialface/` module specifies:
- `PyTorch >= 1.7.1`, `Python 3` in `README.md`
- `dareblopy`, `torchjpeg` in `requirements.txt`

### Challenges with Modern Python (3.12):
1. **`dareblopy` Wheel Incompatibility**:
   - `dareblopy` (v0.0.5) has not been updated since December 2020. Pre-compiled wheels on PyPI exist only for Python 3.5, 3.6, 3.7, and 3.8. There is no source package (`.tar.gz`) on PyPI.
   - Code inspection reveals `dareblopy` is strictly used in `recognition/torchkit/data/parser.py` within `TFRecordSampleParser` to read `.tfrecord` binary archives.
   - It is **not** used by the PartialFace backbone, Discrete Cosine Transform (DCT) operators, or verification routines.
2. **PyTorch Version on Python 3.12**:
   - PyTorch 1.7.1 is obsolete and does not support Python 3.12. Python 3.12 requires PyTorch >= 2.2+. Modern PyTorch (`torch-2.14.1+cpu` / `torchvision-0.29.1+cpu`) was installed.
3. **Legacy Protobuf Generated Files**:
   - `recognition/torchkit/data/example_pb2.py` and `feature_pb2.py` were compiled with an older protobuf compiler version. Modern Google protobuf packages (>= 4.x) reject these descriptors unless `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` is enabled.

---

## 3. Step-by-Step Reproducible Setup

Execute the following commands from the repository root (`/home/racha/FreqID`):

### Step 1: Create Virtual Environment
```bash
python3 -m venv .venv
```

### Step 2: Ensure Local Git Isolation
To avoid modifying tracked files (specifically `.gitignore`, keeping upstream merges clean):
```bash
echo ".venv/" >> .git/info/exclude
```

### Step 3: Install Core ML Packages
For Phase 0 CPU smoke testing and development:
```bash
# Install PyTorch CPU wheels
.venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Install PartialFace dependencies and supporting libraries
.venv/bin/pip install torchjpeg pyyaml scipy opencv-python-headless tensorboard
```

*(Note: For GPU training in Phase 1, PyTorch with CUDA can be installed using `--index-url https://download.pytorch.org/whl/cu124`).*

### Step 4: Configure `dareblopy` Stub & Protobuf Fallback
Provide a clean stub for the legacy `dareblopy` import and configure pure-Python protobuf parsing in `.venv`:

```bash
# Create dareblopy shim in .venv site-packages
cat << 'EOF' > .venv/lib/python3.12/site-packages/dareblopy.py
"""
Stub for dareblopy on Python 3.12.
dareblopy is a 2020 C++ TFRecord reader only compiled for Python 3.5-3.8.
This stub satisfies imports for TFace parser modules when TFRecord dataset reading is not being actively invoked.
"""

class RecordReader:
    def __init__(self, record_path):
        self.record_path = record_path

    def read_record(self, offset):
        raise NotImplementedError(
            "dareblopy C-extension is not available on Python 3.12. "
            "Use modern tfrecord parser or Python 3.8 if legacy TFRecord training files are required."
        )
EOF

# Ensure protobuf runs in compatible mode across all Python processes in .venv
echo 'import os; os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"' > .venv/lib/python3.12/site-packages/protobuf_env.pth
```

---

## 4. Verification Smoke Test

Run the following command to verify the installation:

```bash
PYTHONPATH=recognition .venv/bin/python -c "
import torch
import torch.nn as nn
from tasks.partialface.utils import dct_transform, form_training_batch
from torchkit.backbone import get_model

# Generate dummy RGB images: batch of 2, 3x112x112
x = torch.rand(2, 3, 112, 112)
labels = torch.tensor([105, 204])

# Block DCT and randomized subset sampling
sampled_batch, _ = form_training_batch(x, labels)
assert sampled_batch.shape == (2, 27, 112, 112), f'Expected shape (2, 27, 112, 112), got {sampled_batch.shape}'

# Construct PartialFace IR_18 backbone with adapted 27-channel input layer
backbone = get_model('IR_18')([112, 112])
backbone.input_layer = nn.Sequential(
    nn.Conv2d(27, 64, (3, 3), 1, 1, bias=False),
    nn.BatchNorm2d(64),
    nn.PReLU(64)
)
backbone.eval()

# Forward pass
with torch.no_grad():
    embeddings = backbone(sampled_batch)

assert embeddings.shape == (2, 512), f'Expected embedding shape (2, 512), got {embeddings.shape}'
print('[SUCCESS] Smoke test passed: 27-channel input yielded 512-D embeddings.')
"
```

**Expected output:**
```
[SUCCESS] Smoke test passed: 27-channel input yielded 512-D embeddings.
```
