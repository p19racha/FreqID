# Phase 3 Asset & Model License Audit

This document records all third-party models, weights, and binary assets integrated into Phase 3 (`freqid-client`).

---

## Asset Audit Table

| Asset Name | File Path | Source / Provider | License | Size | SHA-256 Checksum | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- | :--- |
| **YuNet Face Detector (2023mar)** | [`client-sdk/src/freqid_client/models/face_detection_yunet_2023mar.onnx`](file:///home/racha/FreqID/client-sdk/src/freqid_client/models/face_detection_yunet_2023mar.onnx) | OpenCV Zoo (`opencv/opencv_zoo`) | **Apache-2.0** | 232.6 KB (232,589 B) | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` | Lightweight edge face detection and 5-point facial landmark estimation (CPU execution). |

---

## License Compliance Notes

1. **Apache License, Version 2.0**:
   - The YuNet ONNX model is released by OpenCV under the Apache-2.0 license.
   - It permits commercial and non-commercial redistribution, modification, and deployment.
   - Its inclusion complies with FreqID's overall Apache-2.0 licensing.
2. **Download Boundary**:
   - The asset is 232.6 KB, well below the 500 MB threshold, and introduces zero additional dependencies beyond `opencv-python-headless`.
