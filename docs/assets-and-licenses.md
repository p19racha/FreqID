# FreqID Assets, Dependencies & Licensing Inventory

**Version**: 1.0 (Phase 9 Release)  
**Main License**: Apache License, Version 2.0  

---

## 1. Project Licensing & Derivative Work Attribution

FreqID is released under the **Apache License, Version 2.0**.

### 1.1 Upstream Foundation (Tencent/TFace)
FreqID is built upon the open-source **TFace** research platform developed by Tencent Youtu Lab:
- **Original Project**: [Tencent/TFace](https://github.com/Tencent/TFace)
- **Original License**: Apache License, Version 2.0 (see [License.txt](file:///home/racha/FreqID/License.txt))
- **Copyright**: Copyright (c) 2021 Tencent. All rights reserved.

### 1.2 Research & Algorithmic Attributions
FreqID incorporates and adapts the principles and models from the following peer-reviewed research papers:
1. **PartialFace**:
   - *Privacy-Preserving Face Recognition Using Random Frequency Components* (ICCV 2023). Mi et al., Tencent Youtu Lab.
   - *Privacy-Preserving Face Recognition with Learnable Privacy Budgets in Frequency Domain* (ECCV 2022). Mi et al., Tencent Youtu Lab.
2. **SlerpFace**:
   - *SlerpFace: Face Template Protection via Spherical Linear Interpolation* (AAAI 2025). Tencent Youtu Lab.
3. **face.evoLVe**:
   - *High-Performance Face Recognition Library*. Zhao et al. (IR-18 / IR-SE backbone architectures).

---

## 2. Machine Learning Model Artifacts

| Asset Name | Subsystem Location | Origin / Author | License | Description / Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **`partialface_ir_18.onnx`** | `deploy/models/` | Tencent Youtu Lab / FreqID | Apache-2.0 | 27-channel PartialFace IR-18 model exported to ONNX format (512-D embedding). |
| **`face_detection_yunet_2023mar.onnx`** | `client-sdk/src/freqid_client/models/` | OpenCV Zoo (Shiqi Yu et al.) | Apache-2.0 | Lightweight 232 KB YuNet deep face detector for edge 5-point facial landmark alignment. |

*License Note on Datasets*: Standard benchmark evaluation datasets (e.g., LFW, CFP-FP, AgeDB) used during research validation are owned by their respective research institutions. FreqID distribution packages do not bundle raw training datasets.

---

## 3. Third-Party Software Dependencies

All direct runtime dependencies have been audited and verified to conform to permissive open-source licenses (Apache-2.0, MIT, BSD, ISC).

### 3.1 Backend & Client SDK (Python)

| Package | Version | License | Primary Purpose |
| :--- | :--- | :--- | :--- |
| **`fastapi`** | 0.115+ | MIT | Asynchronous REST API framework. |
| **`pydantic`** | 2.10+ | MIT | Strict data validation and schema serialization. |
| **`sqlalchemy`** | 2.0+ | MIT | Database ORM and SQL expression builder. |
| **`asyncpg`** | 0.30+ | Apache-2.0 | High-performance PostgreSQL async I/O driver. |
| **`alembic`** | 1.14+ | MIT | Database schema migration management. |
| **`onnxruntime`** | 1.20+ | MIT | Cross-platform neural network inference runtime. |
| **`cryptography`** | 44.0+ | Apache-2.0 / BSD | AES-256-GCM, Ed25519, X25519, and HKDF primitives. |
| **`argon2-cffi`** | 23.1+ | MIT | Memory-hard password hashing for admin credentials. |
| **`numpy`** | 1.26+ | BSD-3-Clause | Numerical tensor transformations and DCT operations. |
| **`httpx`** | 0.28+ | BSD-3-Clause | HTTP transport client for edge SDK and test suites. |
| **`torch`** (optional) | 2.5+ | Modified BSD | PyTorch research training backend. |

### 3.2 Administrative Web UI (TypeScript / React)

| Package | Version | License | Primary Purpose |
| :--- | :--- | :--- | :--- |
| **`react`** / **`react-dom`** | 18.3.1 | MIT | User interface rendering engine. |
| **`@radix-ui/*`** | 1.1+ / 2.1+ | MIT | Accessible, unstyled UI primitives (dialogs, tooltips). |
| **`@tanstack/react-query`** | 5.62+ | MIT | Server state synchronization and cache management. |
| **`@tanstack/react-table`** | 8.20+ | MIT | Headless table virtualization for devices/audit log. |
| **`tailwindcss`** | 3.4.16 | MIT | Utility-first styling framework. |
| **`lucide-react`** | 0.468+ | ISC | Lightweight interface iconography. |
| **`recharts`** | 2.15+ | MIT | Responsive SVG data visualization charts. |
| **`zod`** | 3.24+ | MIT | Runtime schema validation for forms and API responses. |
| **`date-fns`** | 4.1.0 | MIT | Date manipulation and formatting utilities. |

---

## 4. Fonts & Static Assets

- **Iconography**: [Lucide Icons](https://lucide.dev) — Licensed under ISC.
- **Typography**: Native System Font Stack (`ui-sans-serif, system-ui, sans-serif`). Zero external proprietary web fonts (Google Fonts, Adobe Fonts) are loaded at runtime.
- **Favicon & Logos**: Minimal inline SVG and static assets generated for the FreqID project under Apache-2.0.

---

## 5. Container Base Images

| Image | Base OS | License | Notes |
| :--- | :--- | :--- | :--- |
| **`python:3.12-slim-bookworm`** | Debian 12 | Free Software (Debian Social Contract) | Backend API runtime image. |
| **`node:20-alpine`** | Alpine Linux 3.19 | Free Software (GPL / MIT / BSD) | Multi-stage Admin UI build image. |
| **`nginx:1.27-alpine`** | Alpine Linux 3.19 | 2-Clause BSD (Nginx) | Hardened SPA static server image. |
| **`postgres:16-alpine`** | Alpine Linux 3.19 | PostgreSQL License | Persistence database image. |
| **`caddy:2.8.4-alpine`** | Alpine Linux 3.19 | Apache-2.0 (Caddy) | Ingress reverse proxy image. |
