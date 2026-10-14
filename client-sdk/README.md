# `freqid-client`: Privacy-Preserving Edge Client SDK

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Architectural Isolation](https://img.shields.io/badge/isolation-pure--numpy-success.svg)](#privacy-guarantee)

The edge client SDK for the **FreqID** biometric access system. Running locally on camera-adjacent edge devices (laptops, Raspberry Pi, industrial SBCs), `freqid-client` captures camera frames, detects and aligns faces, verifies image quality, transforms crops into partial frequency representations using 8x8 Block Discrete Cosine Transform (BDCT), and transmits cryptographically protected payloads to the central server.

---

## 🔒 Privacy Guarantee & Zero Raw-Image Persistence

> **Core Privacy Invariant:** Raw spatial video frames and aligned facial crops reside **strictly in transient volatile RAM**. 
> As soon as the 27-channel partial frequency representation is computed, spatial pixel buffers are zeroized and discarded. No unencrypted facial imagery is ever written to disk, logged, or transmitted across the network by default.

Naive inversion of the transmitted partial frequency payload yields only high-frequency noise and ringing artifacts (with DC and low frequencies permanently removed on the device), mathematically preventing identity reconstruction.

---

## 🏗 Pipeline Architecture

```
Camera Sensor (UVC/V4L2)
       │
       ▼
[Raw Camera Frame (BGR)]  ◄── Volatile RAM Only
       │
       ▼
Face Detection & 5 Landmarks (YuNet, 232 KB ONNX, CPU ~2.9 ms)
       │
       ▼
Affine Similarity Alignment (Umeyama Least-Squares to 112x112 canonical frame, ~0.4 ms)
       │
       ▼
Quality Gate Filter (Sharpness variance, luminance range, pose, single-face, ~0.2 ms)
       │
       ▼
8x8 Block DCT & Channel Selection (Pure-NumPy engine, 64 -> 54 kept -> 27 sampled, ~51.9 ms)
       │
       ▼
Zeroize & Discard Spatial Buffers (RAM cleared)
       │
       ▼
Binary Wire Serialization (PartialFacePayload v1 header + float32 array, ~26.9 ms)
       │
       ▼
HTTPS POST Transport (TLS 1.3 / AES-GCM, 128-bit cryptographic nonces, retries)
       │
       ▼
Central FreqID Server (Phase 4)
```

---

## 📦 Installation

`freqid-client` is designed to be lightweight and runs on pure NumPy and OpenCV headless. It does **not** require PyTorch or ONNX Runtime on the edge device.

```bash
# Clone the repository
git clone https://github.com/rachagithub/FreqID.git
cd FreqID

# Activate your virtual environment
source .venv/bin/activate

# Install freqid-core and freqid-client
pip install -e core/
pip install -e client-sdk/
```

Verify that the edge client runs in pure NumPy isolation without loading heavy neural network libraries:
```bash
pytest client-sdk/tests/test_isolation.py
```

---

## 🚀 Command Line Interface (CLI)

The package provides a built-in command-line tool `freqid-client`:

```bash
# 1. Hardware & network diagnostics check
freqid-client check

# 2. Capture a high-quality face and save a protected frequency payload to file
freqid-client capture --out payload.bin

# 3. Live 1:1 biometric verification against the central server
freqid-client verify --user-id alice

# 4. Guided multi-capture enrollment (captures 5 distinct poses/frames)
freqid-client enroll --user-id alice --frames 5
```

---

## 💻 Python SDK Usage

### Single-Frame Edge Pipeline

```python
import cv2
from freqid_client.config import ClientConfig
from freqid_client.pipeline import ClientPipeline

# Initialize edge pipeline (pure NumPy engine)
pipeline = ClientPipeline(config=ClientConfig(min_laplacian_var=60.0))

# Ingest camera frame
frame = cv2.imread("test_face.jpg")

# Process frame through detection -> alignment -> quality gate -> BDCT transform
result = pipeline.process_frame(frame)

if result.success:
    print(f"Generated wire payload: {result.payload_size_bytes} bytes")
    print(f"Pipeline latency: {result.timings.total_ms:.2f} ms")
    payload_bytes = result.payload_bytes
else:
    print(f"Frame rejected: {result.rejection_reason}")
    print(f"Diagnostic message: {result.quality_report.failure_message}")
```

### End-to-End Verification Flow

```python
from freqid_client.auth import StaticTokenAuthenticator
from freqid_client.camera import WebcamSource
from freqid_client.config import ClientConfig
from freqid_client.pipeline import ClientPipeline
from freqid_client.transport import FreqIDTransport

cfg = ClientConfig(server_url="https://auth.company.internal")
pipeline = ClientPipeline(config=cfg)
auth = StaticTokenAuthenticator("edge_shared_secret_token")
transport = FreqIDTransport(server_url=cfg.server_url, device_id=cfg.device_id, auth=auth)

# Capture best frame from webcam
with WebcamSource(camera_index=0) as camera:
    result = pipeline.capture_best_frame(camera, window_frames=5)

if result.success:
    response = transport.verify(payload_bytes=result.payload_bytes, claimed_identity="alice")
    if response["is_match"]:
        print(f"VERIFIED! Match score: {response['similarity']:.4f}")
    else:
        print("ACCESS DENIED: Face did not match template.")
```

---

## ⚙️ Configuration Reference

Settings can be specified via YAML file or environment variables (`FREQID_*`):

| YAML Key | Environment Variable | Default | Description |
| :--- | :--- | :--- | :--- |
| `server_url` | `FREQID_SERVER_URL` | `http://localhost:8000` | HTTPS endpoint of central server |
| `device_id` | `FREQID_DEVICE_ID` | `edge_device_01` | Unique device identifier |
| `camera_index` | `FREQID_CAMERA_INDEX` | `0` | V4L2/UVC camera index |
| `min_face_size` | `FREQID_MIN_FACE_SIZE` | `60` | Minimum bounding box width/height in px |
| `min_laplacian_var` | `FREQID_MIN_LAPLACIAN_VAR` | `80.0` | Minimum sharpness score (variance of Laplacian) |
| `min_brightness` | `FREQID_MIN_BRIGHTNESS` | `40.0` | Minimum mean grayscale luminance |
| `max_brightness` | `FREQID_MAX_BRIGHTNESS` | `220.0` | Maximum mean grayscale luminance |
| `max_yaw_angle` | `FREQID_MAX_YAW_ANGLE` | `15.0` | Maximum estimated yaw tilt in degrees |
| `compress_payload` | `FREQID_COMPRESS_PAYLOAD` | `false` | Apply gzip compression to wire payload |

---

## ⚡ Performance & Benchmarks

Benchmarked on Linux x86_64 CPU (100 repetitions):

| Pipeline Stage | Mean Latency | p50 Latency | p95 Latency | Description |
| :--- | :---: | :---: | :---: | :--- |
| **Face Detection (YuNet)** | 2.90 ms | 2.63 ms | 4.66 ms | 232 KB ONNX model running on OpenCV DNN |
| **Facial Alignment (Umeyama)** | 0.44 ms | 0.42 ms | 0.63 ms | Least-squares 5-point similarity transformation |
| **Quality Gate Filter** | 0.17 ms | 0.17 ms | 0.20 ms | Blur, brightness, face size, and pose gate |
| **Frequency Transform (BDCT)** | 51.93 ms | 51.33 ms | 56.73 ms | Pure-NumPy 8x8 BDCT & channel sampling |
| **Wire Payload Packaging** | 26.92 ms | 26.50 ms | 28.72 ms | Binary framing and header serialization |
| **Total In-Memory Latency** | **82.39 ms** | **81.67 ms** | **88.19 ms** | **12.1 FPS sustained edge throughput** |

---

## ⚠️ Known Limitations & Threat Model

1. **Presentation Attack Detection (PAD / Anti-Spoofing):**
   `freqid-client` in Phase 3 does **not** include active 3D structured light or depth liveness detection. A printed 2D photograph held steady in good illumination will pass the quality gate and get transformed into frequency coefficients. Active multi-spectral or challenge-response liveness is scheduled for Phase 6.
2. **Camera Sensor Trust:**
   The client SDK trusts the local video capture driver. Compromise of the local OS kernel or video buffer injection bypasses edge guarantees. Edge devices must be deployed with physical tampering protections and OS disk encryption.
3. **Pure-NumPy BDCT Compute Bounds:**
   The Pure-NumPy BDCT engine achieves ~12.1 FPS on modern CPU cores. This is optimal for turnstiles, biometric door locks, and kiosks, but not intended for 60 FPS multi-target surveillance streams.
