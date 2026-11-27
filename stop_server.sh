#!/usr/bin/env bash
# Stop the Gunicorn server started by ./start_server.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PID_FILE="${ROOT}/server.pid"

if [[ ! -f "${PID_FILE}" ]]; then
  echo "No PID file found at ${PID_FILE}. Server does not appear to be running."
  exit 0
fi

pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
if [[ -z "${pid}" ]]; then
  echo "PID file is empty. Removing ${PID_FILE}."
  rm -f "${PID_FILE}"
  exit 0
fi

if ! kill -0 "${pid}" 2>/dev/null; then
  echo "Process ${pid} is not running. Removing stale PID file."
  rm -f "${PID_FILE}"
  exit 0
fi

echo "Stopping server (pid ${pid})..."
kill -TERM "${pid}"

# Wait for graceful shutdown; escalate if needed.
for _ in $(seq 1 20); do
  if ! kill -0 "${pid}" 2>/dev/null; then
    rm -f "${PID_FILE}"
    echo "Server stopped."
    exit 0
  fi
  sleep 0.25
done

echo "Server did not exit after TERM; sending KILL..."
kill -KILL "${pid}" 2>/dev/null || true
rm -f "${PID_FILE}"
echo "Server stopped."
