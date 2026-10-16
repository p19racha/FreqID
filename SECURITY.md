# Security Policy

## 1. Supported Versions

Security updates and critical patches are actively provided for the following versions:

| Version | Supported | Status |
| :--- | :--- | :--- |
| **0.1.x** | :white_check_mark: | Current Stable Release (Phase 9) |
| `< 0.1.0` | :x: | Experimental / Developmental Phases |

---

## 2. Reporting a Vulnerability

The FreqID team is committed to ensuring the privacy and cryptographic integrity of our biometric recognition system. If you discover a vulnerability, please report it responsibly.

### 2.1 Private Reporting Channel
**DO NOT file public GitHub issues, pull requests, or discussions for security vulnerabilities.**

Please report vulnerabilities through **GitHub Private Vulnerability Reporting** on the repository:
1. Navigate to the **Security** tab of this repository.
2. Under "Reporting a vulnerability", click **Report a vulnerability**.
3. Alternatively, email the maintainers directly at:  
   `security@freqid.org` (or maintainer contact listed on the GitHub profile).

### 2.2 Information to Include in Your Report
To help us triage and remediate the issue promptly, please include:
- A clear description of the vulnerability, potential impact, and target subsystem (`core`, `client`, `server`, `proxy`, `admin-ui`).
- Step-by-step reproduction instructions or a minimal Proof of Concept (PoC) script.
- The environment configuration (e.g., Docker Compose, OS, hardware).
- Threat model context: specifically how the attack compares against the documented security claims in [docs/security-claims.md](file:///home/racha/FreqID/docs/security-claims.md).

### 2.3 Response Timeline Commitments
- **Initial Acknowledgment**: Within **48 hours** of report receipt.
- **Triage & Severity Assessment**: Within **5 business days**.
- **Remediation & Patch Release**: Dependent on complexity, targeting 30 days for high-severity vulnerabilities before coordinated public disclosure.

---

## 3. Scope of Security Research

### 3.1 In-Scope Vulnerabilities
- Mathematical inversion of PartialFace payloads into recognizable facial imagery (SSIM $> 0.15$ or deep face detector yield $> 5\%$).
- Mathematical inversion or gallery matching of stored encrypted/rotated templates without possession of the private keys.
- Authentication bypass on edge device signatures (`X-Signature`) or administrative sessions.
- Cross-system biometric template linkage ($FLR > 0.1\%$).
- Replay attacks bypassing cryptographic nonce or timestamp validation.
- SQL injection, Remote Code Execution (RCE), or container escape vulnerabilities.

### 3.2 Out-of-Scope Vulnerabilities
- Attacks requiring physical access or kernel-level compromise of the edge camera sensor/bus prior to frequency extraction.
- Attacks requiring simultaneous compromise of both the master AES key and private transform matrix key.
- Volumetric Denial of Service (DoS/DDoS) attacks saturating network bandwidth.
- Social engineering, phishing, or physical attacks against administrators.
- Reports of missing security headers or cookies on development/test servers (`test_config`).

---

## 4. Coordinated Disclosure Policy

FreqID practices **coordinated vulnerability disclosure**:
1. We will collaborate with reporters to verify the issue and develop an effective fix.
2. We will credit the researcher in our release notes and security advisories (unless anonymity is requested).
3. We request that reporters refrain from public disclosure until an official patch has been published and users have had a reasonable window to upgrade.
