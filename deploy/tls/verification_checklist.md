# FreqID Transport Security Verification Checklist

This checklist documents the commands and acceptance criteria to audit that reverse proxies fronting `freqid-server` strictly enforce TLS 1.3 and reject insecure legacy protocols.

---

## 1. Automated OpenSSL Verification Protocol

Run the following commands against the public or internal proxy endpoint (e.g., `https://freqid.internal:443` or `127.0.0.1:8443`):

### 1.1 Verify TLS 1.3 Handshake Succeeds
```bash
openssl s_client -connect 127.0.0.1:443 -tls1_3 -servername freqid.internal </dev/null
```
- **Expected Result**: Handshake succeeds with `Protocol  : TLSv1.3` and `Cipher    : TLS_AES_256_GCM_SHA384` (or `TLS_CHACHA20_POLY1305_SHA256`).

### 1.2 Verify Legacy Protocols (TLS 1.0, 1.1, 1.2) Are Rejected
```bash
# Test TLS 1.2 rejection (when TLS 1.3 is strictly enforced)
openssl s_client -connect 127.0.0.1:443 -tls1_2 -servername freqid.internal </dev/null

# Test TLS 1.1 rejection
openssl s_client -connect 127.0.0.1:443 -tls1_1 -servername freqid.internal </dev/null

# Test TLS 1.0 rejection
openssl s_client -connect 127.0.0.1:443 -tls1 -servername freqid.internal </dev/null
```
- **Expected Result**: Handshake failure / connection closed with `alert protocol version` or `handshake failure`. Zero legacy handshakes established.

### 1.3 Verify Insecure Ciphers Are Refused
```bash
# Attempt weak cipher connection (e.g. RC4, 3DES, CBC)
openssl s_client -connect 127.0.0.1:443 -cipher 'RC4:3DES:AES128-SHA' </dev/null
```
- **Expected Result**: Immediate handshake failure.

---

## 2. Nmap Cipher Enumeration Audit

```bash
nmap --script ssl-enum-ciphers -p 443 freqid.internal
```
- **Expected Result**:
  - `TLSv1.3`:
    - `TLS_AES_256_GCM_SHA384 (ecdh_x25519) - A`
    - `TLS_CHACHA20_POLY1305_SHA256 (ecdh_x25519) - A`
    - `TLS_AES_128_GCM_SHA256 (ecdh_x25519) - A`
  - `TLSv1.2` and lower: Not offered.
  - Overall Grade: **A** or **A+**.

---

## 3. Mutual TLS (mTLS) Client Certificate Verification

When mTLS is activated on edge endpoints:
```bash
# Connecting without client certificate
curl -v https://freqid.internal/api/v1/auth/verify
# Expected: 400 Bad Request ("No required SSL certificate was sent") or 403 Forbidden

# Connecting with valid device certificate
curl -v --cert device.crt --key device.key --cacert ca.crt https://freqid.internal/api/v1/auth/verify
# Expected: 200 OK or normal application response
```
