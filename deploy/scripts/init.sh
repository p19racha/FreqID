#!/usr/bin/env bash
# Copyright 2026 FreqID Authors. Apache-2.0 License.
# init.sh: Production deployment bootstrap and key initialization for FreqID.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${DEPLOY_DIR}/.." && pwd)"

echo "================================================================================"
echo "FreqID Production Stack Initializer & Bootstrap"
echo "================================================================================"

# 1. Prerequisite verification
echo "[*] Checking required system toolchains..."
for cmd in docker openssl; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "[-] Error: Required dependency '$cmd' is not installed or not in PATH." >&2
        exit 1
    fi
done

# Resolve Python interpreter (prefer project virtualenv if available)
if [[ -f "${REPO_ROOT}/.venv/bin/python3" ]]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python3"
elif command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
else
    echo "[-] Error: python3 is required for CA and key management." >&2
    exit 1
fi

if ! docker compose version &>/dev/null; then
    echo "[-] Error: 'docker compose' (v2 plugin) is required." >&2
    exit 1
fi
echo "[+] All required system toolchains are present."

# 2. Directory structure initialization
echo "[*] Initializing deployment directory permissions..."
mkdir -p "${DEPLOY_DIR}/secrets" && chmod 0700 "${DEPLOY_DIR}/secrets"
mkdir -p "${DEPLOY_DIR}/models" && chmod 0755 "${DEPLOY_DIR}/models"
mkdir -p "${DEPLOY_DIR}/tls/certs" && chmod 0700 "${DEPLOY_DIR}/tls/certs"
mkdir -p "${DEPLOY_DIR}/backups" && chmod 0700 "${DEPLOY_DIR}/backups"
echo "[+] Directories initialized with secure POSIX permissions."

# 3. Cryptographic secrets generation
echo "[*] Inspecting secrets inventory..."

# 3a. Database password
DB_PW_FILE="${DEPLOY_DIR}/secrets/db_password.txt"
if [[ ! -f "$DB_PW_FILE" ]]; then
    echo "[*] Generating random PostgreSQL database credentials..."
    openssl rand -hex 24 > "$DB_PW_FILE"
    chmod 0600 "$DB_PW_FILE"
    echo "[+] Generated ${DB_PW_FILE} (mode 0600)."
else
    echo "[i] Existing database credentials detected in secrets/."
fi
DB_PASSWORD="$(cat "$DB_PW_FILE" | tr -d '\r\n')"

# 3b. JWT Secret
JWT_SECRET_FILE="${DEPLOY_DIR}/secrets/jwt_secret.txt"
if [[ ! -f "$JWT_SECRET_FILE" ]]; then
    echo "[*] Generating random HMAC-SHA256 JWT signing secret..."
    openssl rand -hex 32 > "$JWT_SECRET_FILE"
    chmod 0600 "$JWT_SECRET_FILE"
    echo "[+] Generated ${JWT_SECRET_FILE} (mode 0600)."
else
    echo "[i] Existing JWT signing secret detected in secrets/."
fi

# 3c. Master Encryption Key (Phase 8 Envelope Encryption)
MASTER_KEY_FILE="${DEPLOY_DIR}/secrets/master.key"
if [[ ! -f "$MASTER_KEY_FILE" ]]; then
    echo "[*] Generating 256-bit AES-GCM Master Key..."
    openssl rand -base64 32 > "$MASTER_KEY_FILE"
    chmod 0600 "$MASTER_KEY_FILE"
    echo "[+] Generated ${MASTER_KEY_FILE} (mode 0600)."
else
    echo "[i] Existing Master Key detected in secrets/."
fi

# 4. Model checkpoint verification
MODEL_FILE="${DEPLOY_DIR}/models/partialface_ir_18.onnx"
if [[ ! -f "$MODEL_FILE" ]]; then
    SRC_MODEL="${REPO_ROOT}/research/outputs/checkpoints/partialface_ir_18.onnx"
    if [[ -f "$SRC_MODEL" ]]; then
        echo "[*] Copying PartialFace ONNX checkpoint from research outputs..."
        cp "$SRC_MODEL" "$MODEL_FILE"
        echo "[+] Model checkpoint linked to ${MODEL_FILE}."
    else
        echo "[!] Notice: PartialFace model checkpoint not found at ${MODEL_FILE}."
        echo "    Before starting the server, place your trained partialface_ir_18.onnx into deploy/models/."
    fi
else
    echo "[+] Model checkpoint present at ${MODEL_FILE}."
fi

# 5. Environment configuration (.env)
ENV_FILE="${DEPLOY_DIR}/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    echo "[*] Generating .env configuration from template..."
    sed "s/replace_with_strong_database_password_via_init_sh/${DB_PASSWORD}/g" "${DEPLOY_DIR}/.env.example" > "$ENV_FILE"
    chmod 0600 "$ENV_FILE"
    echo "[+] Created ${ENV_FILE} (mode 0600)."
else
    echo "[i] Existing .env detected in deploy/."
fi

# 6. Internal CA Initialization (Optional for mTLS edge device enrollment)
CA_CERT_FILE="${DEPLOY_DIR}/tls/certs/ca.crt"
if [[ ! -f "$CA_CERT_FILE" ]]; then
    echo "[*] Provisioning internal Root CA for mTLS device authentication..."
    if PYTHONPATH="${REPO_ROOT}/backend/src:${PYTHONPATH:-}" "$PYTHON_BIN" "${REPO_ROOT}/scripts/generate_device_cert.py" init-ca --out-dir "${DEPLOY_DIR}/tls/certs" 2>/dev/null; then
        echo "[+] Internal Root CA certificate and key provisioned."
    elif command -v docker &>/dev/null && docker image inspect freqid/server:0.1.0 &>/dev/null; then
        docker run --rm -v "${DEPLOY_DIR}/tls/certs:/certs" -v "${REPO_ROOT}:/repo" -w /repo freqid/server:0.1.0 \
            python3 scripts/generate_device_cert.py init-ca --out-dir /certs
        echo "[+] Internal Root CA certificate and key provisioned via container."
    else
        openssl ecparam -name prime256v1 -genkey -noout -out "${DEPLOY_DIR}/tls/certs/ca.key"
        chmod 0600 "${DEPLOY_DIR}/tls/certs/ca.key"
        openssl req -new -x509 -key "${DEPLOY_DIR}/tls/certs/ca.key" -out "$CA_CERT_FILE" -days 3650 \
            -subj "/C=US/O=FreqID Security Infrastructure/CN=FreqID Internal Root CA"
        echo "[+] Internal Root CA certificate and key provisioned via openssl fallback."
    fi
else
    echo "[i] Existing Root CA certificate detected."
fi

# 7. Compose file syntax validation
echo "[*] Validating Docker Compose configuration..."
(cd "${DEPLOY_DIR}" && docker compose config > /dev/null)
echo "[+] Docker Compose configuration validated successfully."

echo "================================================================================"
echo "[+] FreqID Bootstrap Complete!"
echo ""
echo "Next Steps:"
echo "1. Create initial owner account:"
echo "   (cd deploy && docker compose run --rm --entrypoint freqid-admin server create-owner --username admin)"
echo ""
echo "2. Start the full production stack:"
echo "   (cd deploy && docker compose up -d)"
echo ""
echo "3. Access the Admin Dashboard:"
echo "   Open http://localhost (or your configured DOMAIN_NAME) in your browser."
echo "================================================================================"
