# freqid-core

`freqid-core` is the core privacy-preserving face recognition inference library for FreqID, implementing the PartialFace (ICCV 2023) frequency-domain transform, secure wire serialization, neural backbone evaluation, and biometric matching.

## Architectural Privacy Boundary

`freqid-core` enforces strict isolation between client-side raw image ingestion and server-side vector processing:

- **Client Devices (Edge SDK)**: Converts aligned RGB face images into 27-channel partial frequency tensors via 8x8 BDCT, removes 10 low-frequency channels, samples a random subset, and discards the raw spatial face image immediately. Serializes the result to a compact `PartialFacePayload`.
- **Central Servers (Backend Service)**: Strictly consumes `PartialFacePayload` or 27-channel frequency arrays. Server modules (`Embedder`, `verify`, `identify`) **never import or execute raw image transform code or image decoding libraries**.

## Installation

```bash
# Base package (pure NumPy matching, wire payload serialization, zero torch/image deps):
pip install -e core/

# Full server / edge installation (PyTorch, ONNX Runtime, client transform):
pip install -e "core[all]"
```

## 15-Line Quickstart

```python
import cv2, freqid_core as fq
from freqid_core.embedder import Embedder
from freqid_core.transform import image_to_partial_frequency

# 1. Client: Transform aligned face into privacy-preserving partial frequency payload
raw_face = cv2.cvtColor(cv2.imread("face_aligned.jpg"), cv2.COLOR_BGR2RGB)
freq_tensor = image_to_partial_frequency(raw_face, subset_index=0, perm_index=0)
wire_bytes = fq.PartialFacePayload(freq_tensor.numpy()).to_bytes()  # Sent over network

# 2. Server: Deserialize payload and extract unit-normalized 512-D embedding
server_payload = fq.PartialFacePayload.from_bytes(wire_bytes)
embedder = Embedder.from_checkpoint("checkpoints/partialface_ir_18.onnx", backend="onnx")
embedding = embedder.embed(server_payload)  # shape: (512,), norm: 1.0

# 3. Matching: 1:1 verification against enrolled gallery template
sim, is_match = fq.verify(embedding, gallery_embedding, threshold=0.35)
print(f"Match: {is_match} (Cosine Similarity: {sim:.4f})")
```

## Performance & Model Specs

- **Backbone**: Modified `IR_18` (`input_channels=27`, `output_dim=512`)
- **Parameter Count**: 24,034,176 (24.03M)
- **Model Size**: 91.70 MB (FP32 ONNX) / 183.90 MB (PyTorch `.pth`)
- **CPU Inference Latency (ONNX Runtime, 24-core Intel CPU)**:
  - Batch size 1: **28.26 ms/image** (35.4 FPS) — $3.7\times$ faster than PyTorch CPU
  - Batch size 32: **21.31 ms/image** (46.9 FPS)
- **GPU Inference Latency (PyTorch, RTX 4070 Laptop GPU)**:
  - Batch size 1: **2.42 ms/image** (413.6 FPS)
  - Batch size 32: **0.82 ms/image** (1,220.4 FPS)
- **Wire Payload Size**: 1.29 MB uncompressed (`float32`), ~350 KB compressed.
- **Verification Accuracy (LFW)**: **99.50%** (exact parity with research baseline).

## License & Attribution

Licensed under the Apache License, Version 2.0. Derivative work based on Tencent/TFace (`recognition/tasks/partialface/` and `recognition/torchkit/backbone/model_irse.py`, commit `171ec14562098d5c416e6d1bb90cfaf53b4ae12e`). See [`NOTICE-FREQID.md`](file:///home/racha/FreqID/NOTICE-FREQID.md) for complete attribution.
