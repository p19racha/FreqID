#!/usr/bin/env bash
# Copyright 2026 FreqID Authors. Apache-2.0 License.
# backup.sh: Automated encrypted PostgreSQL backup for FreqID.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${DEPLOY_DIR}/.." && pwd)"

OUT_DIR="${DEPLOY_DIR}/backups"
KEY_FILE="${DEPLOY_DIR}/secrets/backup.key"
RETENTION_DAYS=30

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Takes a consistent PostgreSQL database dump, encrypts it on-the-fly with AES-256-CBC
using PBKDF2 (100,000 iterations), and generates SHA-256 checksums.

Options:
  -o, --out-dir DIR       Output directory for backups (default: ${OUT_DIR})
  -k, --key-file FILE     Path to 256-bit encryption passkey file (default: ${KEY_FILE})
  -r, --retention DAYS    Prune backups older than DAYS (default: ${RETENTION_DAYS}, 0 to disable)
  -h, --help              Show this help message
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -o|--out-dir) OUT_DIR="$2"; shift 2 ;;
        -k|--key-file) KEY_FILE="$2"; shift 2 ;;
        -r|--retention) RETENTION_DAYS="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "[-] Unknown argument: $1" >&2; exit 1 ;;
    esac
done

mkdir -p "$OUT_DIR" && chmod 0700 "$OUT_DIR"

# 1. Verify or generate backup encryption key
if [[ ! -f "$KEY_FILE" ]]; then
    echo "[*] Backup key file not found. Generating new backup key at: ${KEY_FILE}..."
    mkdir -p "$(dirname "$KEY_FILE")" && chmod 0700 "$(dirname "$KEY_FILE")"
    openssl rand -hex 32 > "$KEY_FILE"
    chmod 0600 "$KEY_FILE"
fi

# 2. Extract database connection parameters from deploy/.env or defaults
DB_NAME="freqid"
DB_USER="freqid"
DB_PASSWORD=""

if [[ -f "${DEPLOY_DIR}/.env" ]]; then
    DB_NAME="$(grep -E '^POSTGRES_DB=' "${DEPLOY_DIR}/.env" | cut -d'=' -f2- | tr -d '\r\n"' || echo "freqid")"
    DB_USER="$(grep -E '^POSTGRES_USER=' "${DEPLOY_DIR}/.env" | cut -d'=' -f2- | tr -d '\r\n"' || echo "freqid")"
    DB_PASSWORD="$(grep -E '^POSTGRES_PASSWORD=' "${DEPLOY_DIR}/.env" | cut -d'=' -f2- | tr -d '\r\n"' || echo "")"
fi

if [[ -z "$DB_PASSWORD" && -f "${DEPLOY_DIR}/secrets/db_password.txt" ]]; then
    DB_PASSWORD="$(cat "${DEPLOY_DIR}/secrets/db_password.txt" | tr -d '\r\n')"
fi

if [[ -z "$DB_PASSWORD" ]]; then
    echo "[-] Error: Unable to determine PostgreSQL database password." >&2
    exit 1
fi

TIMESTAMP="$(date -u +%Y%m%d_%H%M%SZ)"
BACKUP_BASENAME="freqid_backup_${TIMESTAMP}.dump.enc"
BACKUP_PATH="${OUT_DIR}/${BACKUP_BASENAME}"
CHECKSUM_PATH="${BACKUP_PATH}.sha256"

echo "[*] Initiating streaming encrypted database backup..."
echo "    Database: ${DB_NAME}"
echo "    User:     ${DB_USER}"
echo "    Target:   ${BACKUP_PATH}"

# 3. Stream pg_dump directly through openssl encryption
# Zero unencrypted dump files touch the filesystem.
set +e
(cd "${DEPLOY_DIR}" && docker compose exec -T -e PGPASSWORD="$DB_PASSWORD" postgres \
    pg_dump -U "$DB_USER" -d "$DB_NAME" -F c --no-owner --no-privileges) | \
    openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -pass "file:${KEY_FILE}" > "$BACKUP_PATH"
DUMP_EXIT_CODE=$?
set -e

if [[ $DUMP_EXIT_CODE -ne 0 || ! -s "$BACKUP_PATH" ]]; then
    echo "[-] Error: Backup failed (exit code: ${DUMP_EXIT_CODE}). Removing partial artifact." >&2
    rm -f "$BACKUP_PATH"
    exit 1
fi

chmod 0600 "$BACKUP_PATH"

# 4. Compute SHA-256 checksum of ciphertext
(cd "$OUT_DIR" && sha256sum "$BACKUP_BASENAME" > "${BACKUP_BASENAME}.sha256")
chmod 0600 "$CHECKSUM_PATH"

BACKUP_SIZE="$(wc -c < "$BACKUP_PATH" | tr -d ' ')"
echo "[+] Backup successfully completed and encrypted."
echo "    File:     ${BACKUP_PATH} (${BACKUP_SIZE} bytes)"
echo "    Checksum: $(cat "$CHECKSUM_PATH")"

# 5. Apply retention policy
if [[ "$RETENTION_DAYS" -gt 0 ]]; then
    echo "[*] Pruning encrypted backups older than ${RETENTION_DAYS} days in ${OUT_DIR}..."
    find "$OUT_DIR" -name "freqid_backup_*.dump.enc*" -type f -mtime "+${RETENTION_DAYS}" -delete
    echo "[+] Backup retention policy applied."
fi
