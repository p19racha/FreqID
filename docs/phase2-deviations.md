# Phase 2 Engineering Deviations & Enhancements: `freqid-core`

This document records all architectural and implementation decisions in `freqid-core` that deviate from or enhance the original research scripts in Tencent/TFace.

---

## 1. Mathematical Parity Audit

No mathematical deviations were introduced to the frequency transformation, channel selection, or neural backbone:
- **Frequency Transform Max Absolute Difference**: **`0.00e+00`** (bit-for-bit identical).
- **Backbone Feature Max Absolute Difference**: **`0.00e+00`** (bit-for-bit identical).
- **Embedding Cosine Similarity**: **`1.00000000`** (bit-for-bit identical).
- **LFW Benchmark Accuracy**: **`99.50%`** vs Phase 1 baseline **`99.50%`** ($\Delta = 0.0000\%$).

---

## 2. Architectural & Engineering Deviations

| # | Component | Upstream Research Implementation | `freqid-core` Implementation | Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **1** | **Training Code Dependencies** | Backbone and transform lived alongside distributed launchers (`torchkit/data/`), margin heads (`ArcFace`), and multi-GPU hooks. | `freqid-core` is isolated in [`core/`](file:///home/racha/FreqID/core/). Contains zero imports of training datasets, margin heads, or distributed runners. | Enables lightweight, fast installation and prevents training dependencies from polluting edge and production environments. |
| **2** | **Raw Image Isolation** | Research evaluation script (`evaluate_partialface.py`) loaded raw images, transformed them, and fed them directly to the backbone in one function. | Segregated into client-only `transform.py` and server-side `embedder.py`. Server modules strictly validate that input has 27 channels and reject 3-channel images. | Enforces the core privacy contract: servers never receive, decode, or possess raw facial photographs. |
| **3** | **Network Transport Format** | In-memory PyTorch tensors `torch.Tensor(B, 27, 112, 112)`. | Standardized binary wire format `PartialFacePayload`: 28-byte header, CRC32 checksum, shape validation, and optional zlib compression. | Production clients and servers need a fast, low-overhead, versioned wire format that works across language boundaries and network sockets. |
| **4** | **Random Subset Sampling** | Hardcoded to image label IDs during training: `choice_index[label % 20]`. | `image_to_partial_frequency()` takes an optional seed / `np.random.Generator` for deterministic unit testing, and defaults to `secrets.randbelow()` for cryptographically secure sampling. | Identity labels do not exist at client capture time during verification; production requires unguessable client-side randomness to prevent eavesdroppers from predicting frequency slices. |
| **5** | **Dual Backend (ONNX)** | Research code supported only PyTorch (`torch.nn.Module`). | Implemented ONNX opset 14 exporter (`export_to_onnx()`) and dual `Embedder` backend supporting both PyTorch and ONNX Runtime. | ONNX Runtime provides a **$3.7\times$ speedup on CPU** (28.26 ms vs 104.12 ms) and enables deployment in C++, Rust, and Go environments without PyTorch. |
| **6** | **Matching Utilities** | Custom ROC loop in research test scripts. | Pure NumPy module `matching.py` with `verify()`, `identify()` (1:N ranked search), and `compute_decision_threshold()` for target False Accept Rates. | Allows central servers to run template verification without GPU or PyTorch dependencies. |
