#!/usr/bin/env bash
# Copyright 2026 FreqID Authors. Apache-2.0 License.
# Pre-commit safety check hook script.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SCRIPT_DIR="${REPO_ROOT}/scripts"

# Prefer repo venv python if available, otherwise system python3
if [ -x "${REPO_ROOT}/.venv/bin/python" ]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
else
    PYTHON_BIN="python3"
fi

exec "${PYTHON_BIN}" "${SCRIPT_DIR}/precommit_check.py" "$@"
