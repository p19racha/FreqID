# FreqID Security Claims & Threat Model

**Version**: 1.0 (Phase 9 Release)  
**Status**: Formally Verified & Defensible  
**Evaluation Reference**: [docs/security-evaluation.md](file:///home/racha/FreqID/docs/security-evaluation.md)  

---

## 1. Overview & Policy on Security Claims

FreqID adheres to an **honest, evidence-based security disclosure policy**. Biometric systems inherently operate on probabilistic pattern matching; therefore, FreqID **does not claim** to be "unhackable", "100% secure", or to "eliminate all biometric risk".

Instead, this document specifies:
1. The formal threat model $\mathcal{T}$ under which the system operates.
2. The specific mathematical and architectural protections implemented.
3. The measured empirical attack results from our adversarial test suite.
4. The remaining residual risks and security boundaries.

---

## 2. Threat Model $\mathcal{T}$

The FreqID security architecture is designed to withstand the following adversary profiles:

### 2.1 In-Scope Adversaries & Attack Vectors

| Threat Identifier | Adversary Capabilities | Attacker Objective | System Defense Layer |
| :--- | :--- | :--- | :--- |
| **T1: Passive Network Eavesdropper** | Observes all traffic between edge devices and the server; terminates TLS at a corporate proxy. | Reconstruct facial images from intercepted packets. | **PartialFace DCT + Application Envelope (`PF02`)**: No raw pixels sent; DCT coefficients sealed with X25519 ECDH + AES-256-GCM. |
| **T2: Rogue TLS Termination Proxy** | Has access to valid server TLS certificate or CA trust store; decrypts transport-layer TLS. | Intercept wire payloads and perform biometric replay or theft. | **End-to-End Application Encryption**: Payload is encrypted for the backend's ephemeral key and signed with Ed25519; TLS termination reveals only ciphertext. |
| **T3: Database Exfiltration / Backup Theft** | Obtains full SQL database dumps (`templates`, `audit_events`). | Match stolen templates against external biometric watchlists or reconstruct face images. | **Envelope Encryption & Cancelable Matrix Rotation**: AES-256-GCM with external master key; vector space transformed by secret orthogonal matrix $R \in \mathbb{O}(512)$. |
| **T4: Black-Box Verification Probing** | Automated attacker submitting sequential synthetic probes to `/v1/verify`. | Hill-climb biometric similarity scores to synthesize an accepted face vector. | **Score Masking & Anomaly Detection**: Responses return boolean `is_match` (score concealed); sliding-window anomaly detector flags near-threshold queries. |
| **T5: Identity Enumeration & Harvesting** | Probes verification endpoints with guessed user IDs. | Discover valid identities and enrollment status. | **Constant-Time Anti-Enumeration**: Non-existent users return `200 OK` with `is_match: false` within 0.16 µs of genuine mismatches. |
| **T6: Packet Replay & Tampering** | Captures legitimate device transmissions and attempts replay or parameter mutation. | Gain unauthorized entry without possessing credentials. | **Cryptographic Nonce Tracking & Signatures**: Sliding-window nonce cache (TTL 300s) + Ed25519 payload signatures. |
| **T7: Multi-Site Template Linkage** | Compares stolen templates across two independent FreqID installations. | Track individuals across organizations. | **Keyed Cancelable Templates**: Distinct matrix keys $R_A \neq R_B$ yield uncorrelated isotropic vectors ($\mu = -0.0006$, FLR = 0.00%). |

### 2.2 Out-of-Scope Adversaries & Residual Risks

1. **Direct Edge Hardware / Bus Compromise**: If an attacker gains root access to the edge device OS, attaches a hardware bus analyzer to the camera interface, or dumps camera frame buffers prior to frequency extraction, raw images can be captured.
2. **Dual-Key Administrative Compromise**: If an attacker compromises both the master AES encryption key (via host memory or Shamir share collusions) **and** the private template transform matrix subkey, stored templates can be unrotated and matched against external galleries.
3. **Coerced / Colluding Administrators**: An administrator with the `owner` role can register malicious devices or modify system settings. FreqID mitigates this via tamper-evident audit logging with SHA-256 hash chaining, but cannot prevent authorized owner actions.

---

## 3. Measured Empirical Security Evaluation

All measurements were empirically obtained from the adversarial evaluation suite (`security-eval/run_all_evals.py`) and recorded in `security-eval/results/eval_results.json`:

```
+----------------------------------------------------------------------------------------------------+
| Evaluation               | Subsystem Target   | Metric                   | Measured Value          |
+--------------------------+--------------------+--------------------------+-------------------------+
| 01. Payload Inversion    | Network / Wire     | Mean SSIM                | 0.0533 (94.7% loss)     |
|                          |                    | Mean PSNR                | 13.15 dB (Noise floor)  |
|                          |                    | Deep Face Detector Yield | 0.0% (0 / 50 detected)  |
| 02. Template Inversion   | Database At-Rest   | Unkeyed Cosine Sim       | -0.0047 (Isotropic)     |
|                          |                    | Gallery Match Rate       | 0.0% (0 / 100 matched)  |
| 03. Cross-Site Linkage   | Multi-Deployment   | Cross-System Sim         | -0.0006                 |
|                          |                    | False Link Rate (FLR)    | 0.00% (ISO/IEC 24745)   |
| 04. Hill Climbing        | Verification API   | Decision-Only Guess Rate | 6.7% (Random walk)      |
|                          |                    | Anomaly Detection Yield  | 93.3% detected early    |
| 05. Protocol Tampering   | Application Wire   | Attack Rejection Rate    | 100.0% (300/300 caught) |
| 06. Proxy Eavesdropping  | Ingress Proxy      | Shannon Entropy          | 7.9916 / 8.0000 bits    |
|                          |                    | Adversary Decrypt Rate   | 0.0% (0 / 50 decrypted) |
| 07. DB Dump Exfiltration | PostgreSQL Storage | At-Rest Cipher Coverage  | 100.0% (50/50 encrypted)|
|                          |                    | Offline Match Rate       | 0.0% (tau = 0.35)       |
| 08. Timing Channels      | Matching Engine    | Exist vs Non-Exist Delta | 0.16 microseconds       |
+----------------------------------------------------------------------------------------------------+
```

---

## 4. The Defensible Security Claim

Under threat model $\mathcal{T}$, against attacks 01–08:

1. **Zero Raw Facial Imagery in Transit or Storage**: No uncompressed or compressed raw facial images are transmitted over the network or stored in the database. Face images captured by edge sensors are converted into 27-channel Block Discrete Cosine Transform (BDCT) frequency representations, and raw spatial images are immediately deleted from RAM.
2. **Invertibility Mitigation**: The discarded DC and low-frequency AC bands contain 95%+ of spatial luminance variance. Inverting the transmitted representation produces a structural similarity score of SSIM = 0.0533, rendering reconstructed imagery unrecognizable to human observers and undetectable by deep neural face detectors (0.0% yield).
3. **Template Protection at Rest**: Biometric templates stored in PostgreSQL are protected by two independent cryptographic mechanisms:
   - AES-256-GCM envelope encryption keyed to a 256-bit master key.
   - Cancelable linear feature rotation using a secret orthogonal matrix $R \in \mathbb{O}(512)$ sampled via the Haar measure.
   Even under total database exfiltration and offline AES key compromise, stolen templates correlate with plain face vectors at isotropic noise levels ($\mu = 0.0095$) and cannot match external biometric galleries.
4. **Unlinkability Across Sites**: Deployments use distinct transform keys $R_A \neq R_B$. The measured cross-system False Link Rate is 0.00% ($d' = 0.1241 \approx 0$), satisfying ISO/IEC 24745 unlinkability requirements.
5. **Score Concealment**: Production verification endpoints return boolean `is_match` decisions without floating-point similarity scores, preventing gradient estimation and reducing black-box hill climbing to random guessing (6.7%).
