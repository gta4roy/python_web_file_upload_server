#!/usr/bin/env bash
# Production-style startup with Gunicorn from the project virtual environment.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

VENV_DIR="${ROOT}/.venv"
GUNICORN="${VENV_DIR}/bin/gunicorn"
PID_FILE="${ROOT}/server.pid"
LOG_DIR="${ROOT}/logs"
ACCESS_LOG="${LOG_DIR}/access.log"
ERROR_LOG="${LOG_DIR}/error.log"

if [[ ! -x "${GUNICORN}" ]]; then
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

HOST="${APP_HOST:-0.0.0.0}"
PORT="${APP_PORT:-5000}"
WORKERS="${GUNICORN_WORKERS:-2}"

if [[ -f "${PID_FILE}" ]]; then
  existing_pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${existing_pid}" ]] && kill -0 "${existing_pid}" 2>/dev/null; then
    echo "Server already running (pid ${existing_pid}). Stop it with ./stop_server.sh first." >&2
    exit 1
  fi
  rm -f "${PID_FILE}"
fi

mkdir -p "${LOG_DIR}"

"${GUNICORN}" \
  --workers "${WORKERS}" \
  --bind "${HOST}:${PORT}" \
  --pid "${PID_FILE}" \
  --daemon \
  --access-logfile "${ACCESS_LOG}" \
  --error-logfile "${ERROR_LOG}" \
  "app:create_app()"

# Gunicorn writes the master PID after daemonizing; give it a moment.
for _ in 1 2 3 4 5; do
  if [[ -f "${PID_FILE}" ]]; then
    break
  fi
  sleep 0.2
done

if [[ ! -f "${PID_FILE}" ]]; then
  echo "Failed to start server (no PID file created). Check ${ERROR_LOG}." >&2
  exit 1
fi

echo "Server started (pid $(cat "${PID_FILE}")) on ${HOST}:${PORT}"
echo "Logs: ${ACCESS_LOG}, ${ERROR_LOG}"
