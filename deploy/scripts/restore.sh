#!/usr/bin/env bash
# Copyright 2026 FreqID Authors. Apache-2.0 License.
# restore.sh: Disaster recovery decryption and database restoration for FreqID.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${DEPLOY_DIR}/.." && pwd)"

BACKUP_FILE=""
KEY_FILE="${DEPLOY_DIR}/secrets/backup.key"
CONFIRM="false"

usage() {
    cat <<EOF
Usage: $(basename "$0") --file BACKUP_FILE [OPTIONS]

Decrypts and restores an encrypted PostgreSQL database dump to the running stack.

Options:
  -f, --file FILE         Path to encrypted backup file (*.dump.enc) [REQUIRED]
  -k, --key-file FILE     Path to encryption key file (default: ${KEY_FILE})
  -y, --yes               Bypass interactive confirmation prompt
  -h, --help              Show this help message
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -f|--file) BACKUP_FILE="$2"; shift 2 ;;
        -k|--key-file) KEY_FILE="$2"; shift 2 ;;
        -y|--yes) CONFIRM="true"; shift 1 ;;
        -h|--help) usage ;;
        *) echo "[-] Unknown argument: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "$BACKUP_FILE" ]]; then
    echo "[-] Error: --file argument is required." >&2
    usage
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "[-] Error: Backup file not found: ${BACKUP_FILE}" >&2
    exit 1
fi

if [[ ! -f "$KEY_FILE" ]]; then
    echo "[-] Error: Backup key file not found: ${KEY_FILE}" >&2
    exit 1
fi

# 1. Verify SHA-256 checksum if present
CHECKSUM_FILE="${BACKUP_FILE}.sha256"
if [[ -f "$CHECKSUM_FILE" ]]; then
    echo "[*] Verifying SHA-256 checksum..."
    (cd "$(dirname "$BACKUP_FILE")" && sha256sum -c "$(basename "$CHECKSUM_FILE")")
    echo "[+] Checksum verification succeeded."
else
    echo "[!] Warning: No .sha256 checksum file found. Proceeding with caution."
fi

# 2. Extract database connection parameters
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

# 3. Confirmation prompt
if [[ "$CONFIRM" != "true" ]]; then
    echo ""
    echo "================================================================================"
    echo "CRITICAL WARNING: RESTORING WILL OVERWRITE EXISTING DATABASE TABLES IN ${DB_NAME}"
    echo "================================================================================"
    read -rp "Are you sure you want to proceed with database restore? [y/N]: " answer
    if [[ "$answer" != "y" && "$answer" != "Y" ]]; then
        echo "[*] Database restoration aborted by user."
        exit 0
    fi
fi

echo "[*] Initiating streaming decryption and database restoration..."
echo "    Source:   ${BACKUP_FILE}"
echo "    Database: ${DB_NAME}"
echo "    User:     ${DB_USER}"

# 4. Stream decryption directly into pg_restore
# Zero unencrypted dump files touch the filesystem.
set +e
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -pass "file:${KEY_FILE}" -in "$BACKUP_FILE" | \
    (cd "${DEPLOY_DIR}" && docker compose exec -T -e PGPASSWORD="$DB_PASSWORD" postgres \
    pg_restore -U "$DB_USER" -d "$DB_NAME" --clean --if-exists --no-owner --no-privileges)
RESTORE_EXIT_CODE=$?
set -e

# Note: pg_restore returns exit code 1 if non-fatal warnings occur (e.g. drop table if exists when table not yet present)
if [[ $RESTORE_EXIT_CODE -ne 0 && $RESTORE_EXIT_CODE -ne 1 ]]; then
    echo "[-] Error: Database restoration failed with exit code: ${RESTORE_EXIT_CODE}." >&2
    exit 1
fi

echo "[+] Database restoration successfully executed."

# 5. Verify database integrity
echo "[*] Verifying database connectivity and administrative accounts..."
(cd "${DEPLOY_DIR}" && docker compose run --rm --no-deps --entrypoint freqid-admin server list-admins)
echo "[+] Disaster recovery restoration verified successfully."
