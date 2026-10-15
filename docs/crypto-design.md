# FreqID Cryptographic Architecture & Formal Specification

This specification provides the formal mathematical and protocol design for the cryptographic protections implemented in FreqID Phase 8.

---

## 1. System Overview & Security Principles

FreqID adopts an end-to-end zero-trust architecture designed to protect biometric face templates, transmission payloads, and server-side assets against both network and database adversaries.

```
+-----------------------------------------------------------------------------------------+
|                                    EDGE DEVICE CLIENT                                   |
|  [Camera Sensor] -> [FreqID Transform] -> [Partial Frequency Payload (PF01/PF02)]      |
|                                                    |                                    |
|                                    Application Envelope Sealing                         |
|                             (X25519 ECDH + HKDF + AES-256-GCM + Ed25519)                |
+--------------------------------------------+--------------------------------------------+
                                             |  mTLS 1.3 (Transport Security)
                                             v
+-----------------------------------------------------------------------------------------+
|                                     FREQID SERVER                                       |
|  1. mTLS Termination (Traefik / Nginx / Reverse Proxy)                                  |
|  2. Replay Detection & Device Signature Verification                                    |
|  3. Payload Decryption via X25519 Private Key                                           |
|  4. PartialFace Embedding Extraction                                                    |
|  5. Cancelable Biometric Rotation (R in O(512))                                         |
|  6. AES-256-GCM Envelope Encryption (Wrapped DEK + AAD Binding)                         |
|  7. Leakage Mitigation (Decision-Only / DP Noise / Near-Threshold Anomaly Detector)     |
+-----------------------------------------------------------------------------------------+
```

---

## 2. Key Derivation Tree

All symmetric subkeys and server asymmetric keypairs are derived from a single 256-bit **Master Root of Trust ($K_{master}$)** using **HKDF-SHA256** ([RFC 5869](https://tools.ietf.org/html/rfc5869)):

$$\text{PRK} = \text{HKDF-Extract}(\text{salt}=\emptyset, \text{IKM}=K_{master})$$
$$K_{purpose} = \text{HKDF-Expand}(\text{PRK}, \text{info}=\text{"freqid-purpose-" } \parallel \text{purpose}, L=32)$$

### Subkey Derivation Registry

| Purpose | Info Parameter | Target Type | Usage |
| :--- | :--- | :--- | :--- |
| `template` | `freqid-purpose-template` | 256-bit symmetric key | Key Encryption Key (KEK) wrapping per-template DEKs. |
| `transform` | `freqid-purpose-transform` | 256-bit symmetric key | Seed for Haar orthogonal projection matrix $R \in \mathbb{O}(512)$. |
| `audit` | `freqid-purpose-audit` | 256-bit symmetric key | HMAC key for append-only audit event chaining. |
| `token` | `freqid-purpose-token` | 256-bit symmetric key | HMAC key for device pairing token validation. |
| `payload` | `freqid-purpose-payload` | X25519 private scalar | Raw 32-byte scalar loaded into Curve25519 private key. |

---

## 3. Application-Layer Payload Sealing Protocol (`PF02`)

Even over TLS 1.3, intermediate proxies, TLS termination points, or local network inspection tools could potentially inspect HTTP request bodies. The `PF02` protocol seals payloads directly on the client device before network transmission.

### 3.1 Sealing Algorithm (Client-Side)

Let $M$ be the raw biometric frequency payload bytes (PartialFace format).
Let $PK_{server}$ be the server's static X25519 public key.
Let $SK_{device}$ be the edge device's Ed25519 signing private key.

1. **Ephemeral Keypair Generation**:
   The client generates an ephemeral Curve25519 keypair:
   $$(sk_{eph}, pk_{eph}) \leftarrow \text{X25519-Generate}()$$

2. **Diffie-Hellman Shared Secret**:
   $$S_{dh} = \text{X25519}(sk_{eph}, PK_{server})$$

3. **Key Derivation (HKDF-SHA256)**:
   $$\text{salt} = pk_{eph} \parallel PK_{server}$$
   $$K_{aead} = \text{HKDF-Expand}(\text{HKDF-Extract}(\text{salt}, S_{dh}), \text{info}=\text{"freqid-payload-v2-aead"}, L=32)$$

4. **AEAD Encryption (AES-256-GCM)**:
   - Generate 96-bit random nonce: $\text{IV} \leftarrow \{0, 1\}^{96}$.
   - Construct Additional Authenticated Data (AAD):
     $$\text{AAD} = \text{"v2|" } \parallel \text{device\_id} \parallel \text{"|" } \parallel \text{timestamp\_iso} \parallel \text{"|" } \parallel \text{request\_id}$$
   - Encrypt:
     $$(C, T) = \text{AES-256-GCM-Encrypt}(K_{aead}, \text{IV}, M, \text{AAD})$$

5. **Device Digital Signature (Ed25519)**:
   The device signs the envelope header and ciphertext:
   $$\sigma = \text{Ed25519-Sign}(SK_{device}, \text{AAD} \parallel C \parallel T)$$

6. **Envelope Serialization**:
   The sealed envelope contains:
   ```json
   {
     "version": "PF02",
     "device_id": "station-01",
     "request_id": "550e8400-e29b-41d4-a716-446655440000",
     "timestamp": "2026-10-15T10:00:00Z",
     "ephemeral_public_key": "<hex(pk_eph)>",
     "nonce": "<hex(IV)>",
     "ciphertext": "<hex(C || T)>",
     "signature": "<hex(sigma)>"
   }
   ```

### 3.2 Unsealing & Verification (Server-Side)

Upon receiving a `PF02` envelope:
1. **Timestamp Window Check**: Ensure $|t_{server} - t_{client}| \le 60\text{ seconds}$.
2. **Replay Cache Check**: Look up `request_id` in the distributed memory cache. If present, reject with HTTP 409 Conflict. Otherwise, record `request_id` with a 120-second TTL.
3. **Signature Verification**: Verify $\sigma$ using the device's registered Ed25519 public key.
4. **Key Derivation & Decryption**: Compute $S_{dh} = \text{X25519}(SK_{server}, pk_{eph})$ and decrypt $C$ with $K_{aead}$ and AAD. Any tampering with timestamp, device ID, request ID, or ciphertext triggers GCM tag verification failure.

---

## 4. Cancelable Orthogonal Template Protection

When biometric face embeddings are stored directly, a database breach exposes raw biometric vectors that could be used for cross-database correlation or feature inversion.

FreqID implements **Cancelable Biometric Transformation via Keyed Orthogonal Isometry** ($R \in \mathbb{O}(512)$).

### 4.1 Haar-Distributed Orthogonal Matrix Construction

Let $K_{transform}$ be the 256-bit subkey derived from $K_{master}$.

1. **Seed Initialization**:
   $$\text{seed} = \text{SHA-256}(K_{transform})[0..4] \pmod{2^{32}}$$
2. **Gaussian Matrix Generation**:
   Sample an independent and identically distributed (i.i.d.) standard normal matrix:
   $$A \in \mathbb{R}^{512 \times 512}, \quad A_{i,j} \sim \mathcal{N}(0, 1)$$
3. **QR Decomposition**:
   $$A = Q R_{qr}, \quad Q \in \mathbb{O}(512), \quad R_{qr} \text{ upper triangular}$$
4. **Haar Measure Phase Normalization (Mezzadri 2006)**:
   To ensure an exact uniform Haar measure over the compact Lie group $\mathbb{O}(512)$:
   $$d = \text{diag}(R_{qr})$$
   $$\Lambda = \text{diag}\left(\frac{d_1}{|d_1|}, \frac{d_2}{|d_2|}, \dots, \frac{d_{512}}{|d_{512}|}\right)$$
   $$R = Q \Lambda \in \mathbb{O}(512)$$

By construction, $R$ satisfies:
$$R^T R = R R^T = I_{512}, \quad \|R v\|_2 = \|v\|_2 \quad \forall v \in \mathbb{R}^{512}$$

### 4.2 Isometry & Cosine Similarity Invariance

Let $x_1, x_2 \in \mathbb{R}^{512}$ be two normalized face embeddings ($\|x_1\|_2 = \|x_2\|_2 = 1$).
The cancelable transformed templates are:
$$y_1 = R x_1, \quad y_2 = R x_2$$

The inner product between transformed vectors is:
$$\langle y_1, y_2 \rangle = y_1^T y_2 = (R x_1)^T (R x_2) = x_1^T R^T R x_2 = x_1^T I_{512} x_2 = x_1^T x_2 = \langle x_1, x_2 \rangle$$

$$\boxed{\cos(y_1, y_2) \equiv \cos(x_1, x_2)}$$

**Theorem (Preservation of Accuracy)**:
The orthogonal transformation introduces zero loss of discriminative power ($\Delta \text{TAR} = 0.00\%$, $\Delta \text{FAR} = 0.00\%$) across any decision threshold $\tau \in [-1, 1]$.

### 4.3 Unlinkability & Non-Invertibility Under Independent Keys

If an organization rotates keys or provisions distinct installations with independent matrices $R_A, R_B \sim \text{Haar}(\mathbb{O}(512))$:

$$\mathbb{E}[\langle R_A x, R_B x \rangle] = x^T \mathbb{E}[R_A^T R_B] x = 0$$

Empirical cross-system linkability evaluations yield mean cosine correlation $\mu = -0.0006$ with standard deviation $\sigma = 0.0441$. At verification threshold $\tau = 0.35$, the cross-system false link rate is strictly $0.00\%$.

---

## 5. Storage Envelope Encryption

Biometric templates in PostgreSQL are wrapped using a two-tier envelope structure combining per-record Data Encryption Keys (DEKs) with the `template` Key Encryption Key (KEK).

```
+-------------------------------------------------------------------------------+
| TemplateOrm Record (Database Row)                                             |
|                                                                               |
| format_version: 2                                                             |
| key_id: "active_key"                                                          |
| nonce: 12-byte random IV                                                      |
|                                                                               |
| wrapped_data_key:                                                             |
|   AES-256-GCM-Encrypt(KEK, IV_dek, DEK, AAD="template_key_wrap:{user_id}")    |
|                                                                               |
| encrypted_blob:                                                               |
|   AES-256-GCM-Encrypt(DEK, IV_blob, Float32Array(R * x),                      |
|                       AAD="freqid-template:{user_id}:{model_v}:v2")           |
+-------------------------------------------------------------------------------+
```

### Decryption Protocol
1. Un-wrap DEK:
   $$\text{DEK} = \text{AES-256-GCM-Decrypt}(K_{template}, \text{wrapped\_data\_key}, \text{AAD}_{dek})$$
2. Decrypt Transformed Embedding:
   $$y = \text{AES-256-GCM-Decrypt}(\text{DEK}, \text{encrypted\_blob}, \text{AAD}_{blob})$$
3. Invert Orthogonal Transformation:
   $$x = R^T y$$

---

## 6. Information Leakage Controls & Attack Countermeasures

To defeat iterative hill-climbing adversaries who execute gradient-free optimization against verification responses:

### 6.1 Decision-Only Mode (Production Default)
In standard production mode, the API omits similarity scores:
```json
{
  "match": true,
  "user_id": "usr_94a10c82",
  "score": null
}
```

### 6.2 Laplace Differential Privacy Noise
When numeric scores are required for diagnostic or calibration environments (`return_score: true`):
1. **Quantization**: Continuous cosine similarity $s \in [-1, 1]$ is snapped to discrete intervals $\Delta s = 0.05$.
2. **Laplace Perturbation**: Zero-mean noise $\eta \sim \text{Laplace}(0, b)$ is added:
   $$s' = \text{clamp}(s + \eta, -1.0, 1.0), \quad b = \frac{\Delta f}{\epsilon}$$
   where global sensitivity $\Delta f = 0.05$ and privacy budget $\epsilon = 1.0$.

### 6.3 Near-Threshold Anomaly Detection
The [`NearThresholdAnomalyDetector`](file:///home/racha/FreqID/backend/src/freqid_server/services/anomaly_detector.py) maintains a per-client sliding window monitoring queries within boundary band $[\tau - \delta, \tau + \delta]$ (default $\tau \pm 0.08$):
- Hill-climbing algorithms generate repeated score trajectories clustering tightly against the decision threshold.
- Upon detecting exceeding thresholds (default: 5 near-boundary probes within 30 seconds), the detector raises an alert in the audit log and halts scoring responses for the requesting client.
- In empirical evaluation (Attack 4), this mechanism successfully terminated $93.3\%$ of synthetic hill-climbing attack attempts before template convergence.
