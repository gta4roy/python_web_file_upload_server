#!/usr/bin/env bash
# Build a single deployable tar for Ubuntu hosts.
#
# The archive includes application code, start/stop scripts, and offline pip
# wheels for all runtime dependencies. On the target host you only need system
# Python 3 (+ venv module); no internet access is required to install deps.
#
# Usage:
#   ./package.sh
#   ./package.sh --output-dir ./dist --name file-upload-server
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

SCRIPT_NAME="$(basename "$0")"
OUTPUT_DIR="${ROOT}/dist"
PACKAGE_NAME="file-upload-server"
PYTHON_BIN="${PYTHON_BIN:-python3}"
KEEP_STAGING=0

usage() {
  cat <<EOF
Usage: ./${SCRIPT_NAME} [options]

Build a self-contained deployment tarball for Ubuntu host installs.

Options:
  -o, --output-dir DIR   Where to write the .tar.gz (default: ./dist)
  -n, --name NAME        Package directory/base name (default: ${PACKAGE_NAME})
  -p, --python BIN       Python used to download wheels (default: python3)
      --keep-staging     Keep the staging directory after tarring
  -h, --help             Show this help

Output:
  dist/<name>-<version>-linux-<arch>-py<ver>.tar.gz

On the deployment server:
  tar -xzf <package>.tar.gz
  cd <package-dir>
  ./install.sh          # creates .venv from bundled wheels (offline)
  # edit config/.env
  ./start_server.sh
  ./stop_server.sh

Target host prerequisites (Ubuntu):
  sudo apt-get install -y python3 python3-venv
EOF
}

die() {
  echo "Error: $*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help|help) usage; exit 0 ;;
    -o|--output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
    -n|--name) PACKAGE_NAME="${2:-}"; shift 2 ;;
    -p|--python) PYTHON_BIN="${2:-}"; shift 2 ;;
    --keep-staging) KEEP_STAGING=1; shift ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

command -v "${PYTHON_BIN}" >/dev/null 2>&1 || die "Python not found: ${PYTHON_BIN}"
command -v tar >/dev/null 2>&1 || die "tar is required"

[[ -f "${ROOT}/requirements-prod.txt" ]] || die "missing requirements-prod.txt"
[[ -d "${ROOT}/app" ]] || die "missing app/ directory"

PY_VERSION="$("${PYTHON_BIN}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_TAG="$("${PYTHON_BIN}" -c 'import sys; print(f"py{sys.version_info.major}{sys.version_info.minor}")')"
ARCH="$(uname -m)"
VERSION="$(date -u +%Y%m%d.%H%M%S)"
if [[ -f "${ROOT}/VERSION" ]]; then
  VERSION="$(tr -d '[:space:]' <"${ROOT}/VERSION")"
fi

BUNDLE_DIR_NAME="${PACKAGE_NAME}-${VERSION}-linux-${ARCH}-${PY_TAG}"
STAGING_ROOT="${OUTPUT_DIR}/.staging-${BUNDLE_DIR_NAME}"
STAGING="${STAGING_ROOT}/${BUNDLE_DIR_NAME}"
TARBALL="${OUTPUT_DIR}/${BUNDLE_DIR_NAME}.tar.gz"

echo "==> Packaging ${BUNDLE_DIR_NAME}"
echo "    python: ${PYTHON_BIN} (${PY_VERSION})"
echo "    arch:   ${ARCH}"
echo "    out:    ${TARBALL}"

rm -rf "${STAGING_ROOT}"
mkdir -p "${STAGING}" "${OUTPUT_DIR}"

echo "==> Copying application files"
mkdir -p \
  "${STAGING}/app" \
  "${STAGING}/config" \
  "${STAGING}/data" \
  "${STAGING}/storage/files" \
  "${STAGING}/storage/temp" \
  "${STAGING}/vendor/wheels" \
  "${STAGING}/logs"

# Application package (exclude bytecode caches)
(
  cd "${ROOT}/app"
  tar -cf - \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    .
) | (cd "${STAGING}/app" && tar -xf -)

cp -a "${ROOT}/run.py" "${STAGING}/"
cp -a "${ROOT}/openapi.yaml" "${STAGING}/"
cp -a "${ROOT}/requirements-prod.txt" "${STAGING}/requirements.txt"
cp -a "${ROOT}/config/.env.example" "${STAGING}/config/.env.example"
cp -a "${ROOT}/config/.env.example" "${STAGING}/config/.env"

# Empty runtime placeholders
touch "${STAGING}/storage/files/.gitkeep" "${STAGING}/storage/temp/.gitkeep" "${STAGING}/data/.gitkeep"

# Record build metadata
cat >"${STAGING}/VERSION" <<EOF
${VERSION}
EOF

cat >"${STAGING}/BUILD_INFO" <<EOF
package_name=${PACKAGE_NAME}
version=${VERSION}
built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
built_on_host=$(hostname)
build_os=$(uname -s)
build_arch=${ARCH}
python=${PY_VERSION}
python_bin=${PYTHON_BIN}
EOF

echo "==> Downloading offline wheels (requires network on build machine)"
BUILD_VENV="${STAGING_ROOT}/.build-venv"
"${PYTHON_BIN}" -m venv "${BUILD_VENV}"
# shellcheck disable=SC1091
source "${BUILD_VENV}/bin/activate"
pip install --upgrade pip wheel setuptools >/dev/null
pip download \
  -r "${ROOT}/requirements-prod.txt" \
  -d "${STAGING}/vendor/wheels" \
  --prefer-binary
# Ensure installer tooling is present offline as well
pip download pip setuptools wheel -d "${STAGING}/vendor/wheels" --prefer-binary
deactivate

WHEEL_COUNT="$(find "${STAGING}/vendor/wheels" -type f | wc -l | tr -d ' ')"
[[ "${WHEEL_COUNT}" -gt 0 ]] || die "no wheels downloaded into vendor/wheels"
echo "    bundled wheels: ${WHEEL_COUNT}"

echo "==> Writing deploy scripts"
cat >"${STAGING}/install.sh" <<'EOF'
#!/usr/bin/env bash
# Create .venv from bundled offline wheels (no internet required).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${ROOT}/.venv"
WHEELS_DIR="${ROOT}/vendor/wheels"

die() { echo "Error: $*" >&2; exit 1; }

command -v "${PYTHON_BIN}" >/dev/null 2>&1 || die \
  "Python not found (${PYTHON_BIN}). On Ubuntu: sudo apt-get install -y python3 python3-venv"

"${PYTHON_BIN}" - <<'PY' || die "python3-venv is missing. On Ubuntu: sudo apt-get install -y python3-venv"
import venv
PY

[[ -d "${WHEELS_DIR}" ]] || die "missing vendor/wheels — package is incomplete"
[[ -f "${ROOT}/requirements.txt" ]] || die "missing requirements.txt"

if [[ -d "${VENV_DIR}" ]]; then
  echo "Removing existing virtualenv at ${VENV_DIR}"
  rm -rf "${VENV_DIR}"
fi

echo "Creating virtualenv with ${PYTHON_BIN}..."
"${PYTHON_BIN}" -m venv "${VENV_DIR}"

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade --no-index --find-links="${WHEELS_DIR}" pip setuptools wheel
python -m pip install --no-index --find-links="${WHEELS_DIR}" -r "${ROOT}/requirements.txt"
deactivate

if [[ ! -f "${ROOT}/config/.env" ]]; then
  cp "${ROOT}/config/.env.example" "${ROOT}/config/.env"
  echo "Created config/.env from example — edit ENCRYPTION_KEY before production use."
fi

mkdir -p "${ROOT}/storage/files" "${ROOT}/storage/temp" "${ROOT}/data" "${ROOT}/logs"

echo
echo "Install complete."
echo "  1) Edit config/.env (ENCRYPTION_KEY, APP_PORT, STORAGE_DIR, ...)"
echo "  2) ./start_server.sh"
echo "  3) ./stop_server.sh"
EOF

cat >"${STAGING}/start_server.sh" <<'EOF'
#!/usr/bin/env bash
# Start Gunicorn using the package-local virtualenv.
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
  echo "Virtualenv not found. Running ./install.sh ..."
  "${ROOT}/install.sh"
fi

[[ -x "${GUNICORN}" ]] || { echo "Error: gunicorn missing after install" >&2; exit 1; }

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

mkdir -p "${LOG_DIR}" "${STORAGE_DIR:-./storage/files}" "${TEMP_DIR:-./storage/temp}" \
  "$(dirname "${METADATA_FILE:-./data/file_metadata.json}")"

"${GUNICORN}" \
  --workers "${WORKERS}" \
  --bind "${HOST}:${PORT}" \
  --pid "${PID_FILE}" \
  --daemon \
  --access-logfile "${ACCESS_LOG}" \
  --error-logfile "${ERROR_LOG}" \
  "app:create_app()"

for _ in 1 2 3 4 5 6 7 8 9 10; do
  if [[ -f "${PID_FILE}" ]]; then
    break
  fi
  sleep 0.2
done

if [[ ! -f "${PID_FILE}" ]]; then
  echo "Failed to start server (no PID file). Check ${ERROR_LOG}." >&2
  exit 1
fi

echo "Server started (pid $(cat "${PID_FILE}")) on ${HOST}:${PORT}"
echo "Logs: ${ACCESS_LOG}, ${ERROR_LOG}"
EOF

cat >"${STAGING}/stop_server.sh" <<'EOF'
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
EOF

cat >"${STAGING}/run.sh" <<'EOF'
#!/usr/bin/env bash
# Foreground Flask development server using package-local virtualenv.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

VENV_DIR="${ROOT}/.venv"
PYTHON="${VENV_DIR}/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  echo "Virtualenv not found. Running ./install.sh ..."
  "${ROOT}/install.sh"
fi

if [[ -f config/.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source config/.env
  set +a
fi

exec "${PYTHON}" run.py
EOF

cat >"${STAGING}/DEPLOY.md" <<EOF
# File Upload Server — Deployment Bundle

Built for Ubuntu host deployment. Runtime pip dependencies are bundled under
\`vendor/wheels\` for offline install.

## Host prerequisites

\`\`\`bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv
\`\`\`

Python **${PY_VERSION}+** recommended (bundle wheels were resolved with ${PY_VERSION}).

## Install & run

\`\`\`bash
tar -xzf ${BUNDLE_DIR_NAME}.tar.gz
cd ${BUNDLE_DIR_NAME}

./install.sh

# Set a strong key before production use:
#   python3 -c "import secrets; print(secrets.token_hex(32))"
nano config/.env

./start_server.sh
curl -s http://127.0.0.1:5000/health

./stop_server.sh
\`\`\`

\`./start_server.sh\` will call \`./install.sh\` automatically if \`.venv\` is missing.

## Configuration

See \`config/.env\`:

- \`APP_HOST\` / \`APP_PORT\`
- \`MAX_FILE_SIZE_MB\`
- \`STORAGE_DIR\` / \`TEMP_DIR\`
- \`METADATA_FILE\`
- \`ENCRYPTION_ENABLED\` / \`ENCRYPTION_KEY\`

## Layout

\`\`\`
app/                 Flask application
config/              .env and example
vendor/wheels/       Offline pip wheels
storage/files/       Uploaded file content
storage/temp/        Temp upload workspace
data/                Metadata JSON
logs/                Gunicorn logs
install.sh           Offline venv bootstrap
start_server.sh      Start Gunicorn (daemon)
stop_server.sh       Stop Gunicorn
run.sh               Foreground Flask (dev)
\`\`\`
EOF

chmod +x \
  "${STAGING}/install.sh" \
  "${STAGING}/start_server.sh" \
  "${STAGING}/stop_server.sh" \
  "${STAGING}/run.sh"

echo "==> Creating tarball"
tar -C "${STAGING_ROOT}" -czf "${TARBALL}" "${BUNDLE_DIR_NAME}"

# Cleanup build venv / staging
rm -rf "${BUILD_VENV}"
if [[ "${KEEP_STAGING}" -eq 0 ]]; then
  rm -rf "${STAGING_ROOT}"
else
  echo "Staging kept at ${STAGING}"
fi

BYTES="$(wc -c <"${TARBALL}" | tr -d ' ')"
echo
echo "==> Package ready"
echo "    ${TARBALL}"
echo "    size: ${BYTES} bytes"
echo
echo "Copy to server and extract:"
echo "  scp ${TARBALL} user@server:/opt/"
echo "  ssh user@server 'cd /opt && tar -xzf $(basename "${TARBALL}") && cd ${BUNDLE_DIR_NAME} && ./install.sh && ./start_server.sh'"
