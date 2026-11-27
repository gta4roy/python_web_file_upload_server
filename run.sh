#!/usr/bin/env bash
# Development server using the project virtual environment.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

VENV_DIR="${ROOT}/.venv"
PYTHON="${VENV_DIR}/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  echo "Virtual environment not found at ${VENV_DIR}" >&2
  echo "Run ./setup.sh first." >&2
  exit 1
fi

if [[ -f config/.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source config/.env
  set +a
fi

exec "${PYTHON}" run.py
