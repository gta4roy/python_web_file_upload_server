#!/usr/bin/env bash
# Trigger Grafana k6 load test against the File Upload API.
#
# Arguments:
#   users       Number of parallel virtual users (k6 --vus)
#   iterations  Total iterations across all users (k6 --iterations)
#   file_size   Payload size to generate (bytes, or human form: 64K, 1M, 10MB)
#
# Each iteration: upload → list → download → delete
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

SCRIPT_NAME="$(basename "$0")"
K6_SCRIPT="${ROOT}/loadtest/file_api_load.js"
PAYLOAD_DIR="${ROOT}/loadtest/payloads"
BASE_URL="${BASE_URL:-http://127.0.0.1:5000}"
ENCRYPT="${ENCRYPT:-false}"
OUT_DIR="${ROOT}/loadtest/results"

usage() {
  cat <<EOF
Usage:
  ./${SCRIPT_NAME} <users> <iterations> <file_size>
  ./${SCRIPT_NAME} --users N --iterations N --file-size SIZE [options]
  ./${SCRIPT_NAME} --help

Arguments:
  users         Parallel virtual users (k6 VUs)
  iterations    Total iterations shared across all users
  file_size     Size of randomly generated upload file
                Accepts integers (bytes) or suffixes: K/KB, M/MB, G/GB
                Examples: 1024, 64K, 1M, 10MB

Options:
  -u, --base-url URL     Target API base URL (default: ${BASE_URL}, or \$BASE_URL)
  -e, --encrypt BOOL     Upload with encrypt=true|false (default: ${ENCRYPT})
  -h, --help             Show this help

Environment:
  BASE_URL   Same as --base-url
  ENCRYPT    Same as --encrypt
  K6_BIN     Path to k6 binary (default: k6 on PATH)

Examples:
  ./${SCRIPT_NAME} 5 50 64K
  ./${SCRIPT_NAME} --users 10 --iterations 200 --file-size 1M
  ./${SCRIPT_NAME} 20 100 512K --encrypt true
  BASE_URL=http://127.0.0.1:5000 ./${SCRIPT_NAME} 5 25 1M

Prerequisites:
  - Server running (./start_server.sh)
  - k6 installed: https://grafana.com/docs/k6/latest/set-up/install-k6/
EOF
}

die() {
  echo "Error: $*" >&2
  exit 1
}

# Convert 64K / 1M / 10MB / 1024 → bytes
parse_size_to_bytes() {
  local raw="${1:-}"
  [[ -n "${raw}" ]] || die "file_size is required"

  if [[ "${raw}" =~ ^[0-9]+$ ]]; then
    echo "${raw}"
    return
  fi

  local normalized
  normalized="$(echo "${raw}" | tr '[:lower:]' '[:upper:]')"

  if [[ "${normalized}" =~ ^([0-9]+)(K|KB|M|MB|G|GB)$ ]]; then
    local n="${BASH_REMATCH[1]}"
    local unit="${BASH_REMATCH[2]}"
    case "${unit}" in
      K|KB) echo $((n * 1024)) ;;
      M|MB) echo $((n * 1024 * 1024)) ;;
      G|GB) echo $((n * 1024 * 1024 * 1024)) ;;
    esac
    return
  fi

  die "invalid file_size '${raw}' (use bytes or K/KB/M/MB/G/GB)"
}

human_bytes() {
  local bytes="$1"
  if (( bytes >= 1073741824 )); then
    awk -v b="${bytes}" 'BEGIN { printf "%.2f GiB", b/1073741824 }'
  elif (( bytes >= 1048576 )); then
    awk -v b="${bytes}" 'BEGIN { printf "%.2f MiB", b/1048576 }'
  elif (( bytes >= 1024 )); then
    awk -v b="${bytes}" 'BEGIN { printf "%.2f KiB", b/1024 }'
  else
    echo "${bytes} B"
  fi
}

# Generate a random binary file of exactly SIZE bytes.
generate_random_file() {
  local dest="$1"
  local size_bytes="$2"

  mkdir -p "$(dirname "${dest}")"
  rm -f "${dest}"

  if [[ "${size_bytes}" -eq 0 ]]; then
    : >"${dest}"
    return
  fi

  # Prefer head -c (fast), then openssl, then dd.
  if head -c "${size_bytes}" /dev/urandom >"${dest}" 2>/dev/null; then
    :
  elif command -v openssl >/dev/null 2>&1; then
    openssl rand -out "${dest}" "${size_bytes}"
  else
    local bs=1048576
    local full=$((size_bytes / bs))
    local rem=$((size_bytes % bs))
    : >"${dest}"
    if (( full > 0 )); then
      dd if=/dev/urandom of="${dest}" bs="${bs}" count="${full}" status=none conv=notrunc
    fi
    if (( rem > 0 )); then
      dd if=/dev/urandom bs="${rem}" count=1 status=none >>"${dest}"
    fi
  fi

  local actual
  actual="$(wc -c <"${dest}" | tr -d ' ')"
  [[ "${actual}" -eq "${size_bytes}" ]] || die "generated file size mismatch: expected ${size_bytes}, got ${actual}"
}

USERS=""
ITERATIONS=""
FILE_SIZE_RAW=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help|help)
      usage
      exit 0
      ;;
    --users)
      USERS="${2:-}"; shift 2 ;;
    --iterations)
      ITERATIONS="${2:-}"; shift 2 ;;
    --file-size)
      FILE_SIZE_RAW="${2:-}"; shift 2 ;;
    -u|--base-url)
      BASE_URL="${2:-}"; shift 2 ;;
    -e|--encrypt)
      ENCRYPT="${2:-}"; shift 2 ;;
    -*)
      die "unknown option '$1' (try --help)" ;;
    *)
      # Positional: users iterations file_size
      if [[ -z "${USERS}" ]]; then
        USERS="$1"
      elif [[ -z "${ITERATIONS}" ]]; then
        ITERATIONS="$1"
      elif [[ -z "${FILE_SIZE_RAW}" ]]; then
        FILE_SIZE_RAW="$1"
      else
        die "unexpected argument '$1' (try --help)"
      fi
      shift
      ;;
  esac
done

[[ -n "${USERS}" && -n "${ITERATIONS}" && -n "${FILE_SIZE_RAW}" ]] \
  || { usage; echo; die "users, iterations, and file_size are required"; }

[[ "${USERS}" =~ ^[1-9][0-9]*$ ]] || die "users must be a positive integer"
[[ "${ITERATIONS}" =~ ^[1-9][0-9]*$ ]] || die "iterations must be a positive integer"
case "${ENCRYPT}" in
  true|false) ;;
  *) die "--encrypt must be true or false" ;;
esac

[[ -f "${K6_SCRIPT}" ]] || die "k6 script not found: ${K6_SCRIPT}"

K6_BIN="${K6_BIN:-k6}"
command -v "${K6_BIN}" >/dev/null 2>&1 || die "k6 not found on PATH. Install from https://grafana.com/docs/k6/latest/set-up/install-k6/"

SIZE_BYTES="$(parse_size_to_bytes "${FILE_SIZE_RAW}")"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE_NAME="loadtest-${FILE_SIZE_RAW}-${TIMESTAMP}.bin"
# sanitize filename characters that are awkward in paths
FILE_NAME="${FILE_NAME//\//_}"
PAYLOAD_PATH="${PAYLOAD_DIR}/${FILE_NAME}"

echo "==> Generating random payload"
echo "    size: ${FILE_SIZE_RAW} ($(human_bytes "${SIZE_BYTES}") / ${SIZE_BYTES} bytes)"
echo "    path: ${PAYLOAD_PATH}"
generate_random_file "${PAYLOAD_PATH}" "${SIZE_BYTES}"

# Quick connectivity check
if ! curl -sS -o /dev/null -w "%{http_code}" "${BASE_URL%/}/health" | grep -q '^200$'; then
  die "server not reachable at ${BASE_URL}/health — start it with ./start_server.sh"
fi

mkdir -p "${OUT_DIR}"
RESULT_JSON="${OUT_DIR}/k6-summary-${TIMESTAMP}.json"

echo "==> Starting k6 load test"
echo "    base_url:   ${BASE_URL}"
echo "    users:      ${USERS}"
echo "    iterations: ${ITERATIONS}"
echo "    encrypt:    ${ENCRYPT}"
echo "    script:     ${K6_SCRIPT}"
echo "    summary:    ${RESULT_JSON}"
echo

BASE_URL="${BASE_URL}" \
DATA_FILE="${PAYLOAD_PATH}" \
FILE_NAME="${FILE_NAME}" \
ENCRYPT="${ENCRYPT}" \
  "${K6_BIN}" run \
    --vus "${USERS}" \
    --iterations "${ITERATIONS}" \
    --summary-export "${RESULT_JSON}" \
    "${K6_SCRIPT}"

echo
echo "==> Done"
echo "    payload kept at: ${PAYLOAD_PATH}"
echo "    k6 summary:      ${RESULT_JSON}"
