#!/usr/bin/env bash
# Copyright 2026 FreqID Authors. Apache-2.0 License.
# run_ci_local.sh: Locally replicates the full GitHub Actions CI pipeline.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

echo "================================================================================"
echo "                   FreqID Local CI Pipeline Test Suite                          "
echo "================================================================================"

# ------------------------------------------------------------------------------
# 1. Pre-commit Hygiene & Privacy Scan
# ------------------------------------------------------------------------------
echo -e "\n[*] [1/4] Running pre-commit safety check (zero raw images / secrets)..."
python3 scripts/precommit_check.py --all

# ------------------------------------------------------------------------------
# 2. Admin UI (React / TypeScript / Vitest)
# ------------------------------------------------------------------------------
echo -e "\n[*] [2/4] Testing Admin UI (Node/TypeScript)..."
if command -v pnpm &>/dev/null; then
    pnpm --dir admin-ui check:no-camera
    pnpm --dir admin-ui lint
    pnpm --dir admin-ui typecheck
    pnpm --dir admin-ui test
    pnpm --dir admin-ui build
    echo "[+] Admin UI suite passed."
else
    echo "[!] pnpm not installed locally. Skipping local UI check (runs in CI)."
fi

# ------------------------------------------------------------------------------
# 3. Python Linters & Formatting
# ------------------------------------------------------------------------------
echo -e "\n[*] [3/4] Running Python linters (ruff)..."
if command -v ruff &>/dev/null; then
    ruff check core client-sdk backend
    ruff format --check core client-sdk backend
elif command -v uvx &>/dev/null || [ -x "$HOME/.local/bin/uvx" ]; then
    UVX_BIN="$(command -v uvx || echo "$HOME/.local/bin/uvx")"
    "${UVX_BIN}" ruff check core client-sdk backend
    "${UVX_BIN}" ruff format --check core client-sdk backend
fi
echo "[+] Python linting passed."

# ------------------------------------------------------------------------------
# 4. Python Test Suites via Isolated Docker Environment
# ------------------------------------------------------------------------------
echo -e "\n[*] [4/4] Executing Python test suites (core, client-sdk, backend)..."

POSTGRES_CONTAINER_NAME="freqid-ci-postgres-$RANDOM"

cleanup() {
    docker rm -f "${POSTGRES_CONTAINER_NAME}" &>/dev/null || true
}
trap cleanup EXIT

echo "[*] Spinning up ephemeral test PostgreSQL container..."
docker run -d --name "${POSTGRES_CONTAINER_NAME}" \
    -e POSTGRES_DB=freqid \
    -e POSTGRES_USER=freqid_admin \
    -e POSTGRES_PASSWORD=freqid_admin_dev_password \
    -p 54322:5432 \
    postgres:16-alpine >/dev/null

echo "[*] Waiting for PostgreSQL readiness..."
for i in {1..30}; do
    if docker exec "${POSTGRES_CONTAINER_NAME}" pg_isready -U freqid_admin -d freqid &>/dev/null; then
        break
    fi
    sleep 1
done

echo "[*] Running test suites inside python:3.12-slim container..."
docker run --rm --network host \
    -v "${REPO_ROOT}:/repo" \
    -w /repo \
    -e FREQID_DATABASE_URL="postgresql+asyncpg://freqid_admin:freqid_admin_dev_password@127.0.0.1:54322/freqid" \
    -e FREQID_SERVER_DATABASE_URL="postgresql+asyncpg://freqid_admin:freqid_admin_dev_password@127.0.0.1:54322/freqid" \
    python:3.12-slim bash -c "
set -euo pipefail

pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu >/dev/null 2>&1
pip install pytest pytest-asyncio asyncpg sqlalchemy greenlet pydantic pydantic-settings cryptography argon2-cffi pyjwt shamir-mnemonic onnx onnxruntime onnxscript torchjpeg httpx numpy pyyaml uvicorn fastapi alembic opencv-python-headless pytest-cov >/dev/null 2>&1

echo '[*] Bootstrapping model checkpoints and database schema...'
python backend/scripts/init_test_env.py

echo '[*] Running core tests...'
PYTHONPATH=core/src pytest core/tests/ -v

echo '[*] Running client-sdk tests...'
PYTHONPATH=core/src:client-sdk/src pytest client-sdk/tests/ -v

echo '[*] Running backend tests...'
PYTHONPATH=core/src:client-sdk/src:backend/src pytest backend/tests/ -v
"

echo -e "\n================================================================================"
echo "[+] SUCCESS: All CI checks and test suites passed locally!"
echo "================================================================================"
