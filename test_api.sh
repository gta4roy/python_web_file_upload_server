#!/usr/bin/env bash
# Manual / smoke test client for the File Upload API (openapi.yaml).
#
# Exercises:
#   POST   /api/v1/files
#   GET    /api/v1/files
#   DELETE /api/v1/files/{fileId}
#   GET    /api/v1/files/{fileId}/content
#
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
BASE_URL="${BASE_URL:-http://127.0.0.1:5000}"
REQUEST_ID=""
VERBOSE=0
RESP_BODY=""
RESP_STATUS=""

usage() {
  cat <<EOF
Usage: ./${SCRIPT_NAME} [global options] <command> [command options]

Global options:
  -u, --base-url URL     API base URL (default: ${BASE_URL}, or \$BASE_URL)
  -r, --request-id ID    Optional X-Request-Id header value
  -v, --verbose          Print curl request details
  -h, --help             Show this help

Commands (mapped to OpenAPI operations):

  help
      Show this help.

  health
      GET /health  (liveness; not in OpenAPI but useful for connectivity)

  upload --file PATH [--encrypt true|false]
      POST /api/v1/files
      Required:
        -f, --file PATH          File to upload
      Optional:
        -e, --encrypt BOOL       Encrypt before store (default: false)

  list [--limit N] [--offset N]
      GET /api/v1/files
      Optional:
        -l, --limit N            Page size 1..100 (default: 20)
        -o, --offset N           Records to skip (default: 0)

  download --id FILE_ID [--out PATH]
      GET /api/v1/files/{fileId}/content
      Required:
        -i, --id FILE_ID         File UUID
      Optional:
        -o, --out PATH           Save body to PATH
                                 (default: Content-Disposition filename or <id>.bin)

  delete --id FILE_ID
      DELETE /api/v1/files/{fileId}
      Required:
        -i, --id FILE_ID         File UUID

  all [--file PATH] [--encrypt true|false] [--keep]
      Full smoke flow: upload → list → download → delete → verify 404
      Optional:
        -f, --file PATH          Sample file (default: creates a temp file)
        -e, --encrypt BOOL       Encrypt on upload (default: false)
        -k, --keep               Skip the final delete step

Examples:
  ./${SCRIPT_NAME} help
  ./${SCRIPT_NAME} health
  ./${SCRIPT_NAME} upload --file ./README.md
  ./${SCRIPT_NAME} upload --file ./README.md --encrypt true
  ./${SCRIPT_NAME} list --limit 10 --offset 0
  ./${SCRIPT_NAME} download --id <uuid> --out ./downloaded.md
  ./${SCRIPT_NAME} delete --id <uuid>
  ./${SCRIPT_NAME} all --file ./README.md --encrypt true
  BASE_URL=http://127.0.0.1:5000 ./${SCRIPT_NAME} all
EOF
}

die() {
  echo "Error: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "'$1' is required but not installed"
}

api_url() {
  local path="$1"
  echo "${BASE_URL%/}${path}"
}

# Append shared curl options into the named array.
build_curl_args() {
  local -n _out="$1"
  _out+=(-sS)
  if [[ "${VERBOSE}" -eq 1 ]]; then
    _out+=(-v)
  fi
  if [[ -n "${REQUEST_ID}" ]]; then
    _out+=(-H "X-Request-Id: ${REQUEST_ID}")
  fi
}

# Run curl with -w status trailer; sets RESP_BODY / RESP_STATUS.
run_json_request() {
  local -a args=()
  build_curl_args args
  args+=(-w $'\nHTTP_STATUS:%{http_code}')
  args+=("$@")

  local output
  output="$(curl "${args[@]}")"
  RESP_STATUS="$(printf '%s' "${output}" | awk -F: '/^HTTP_STATUS:/{print $2}' | tr -d '\r')"
  RESP_BODY="$(printf '%s' "${output}" | sed '/^HTTP_STATUS:/d')"
}

print_response() {
  local label="$1"
  echo "=== ${label} ==="
  echo "HTTP ${RESP_STATUS}"
  if [[ -z "${RESP_BODY}" ]]; then
    echo "(empty body)"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    if printf '%s' "${RESP_BODY}" | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null; then
      printf '%s' "${RESP_BODY}" | python3 -m json.tool
      return
    fi
  fi
  printf '%s\n' "${RESP_BODY}"
}

expect_status() {
  local expected="$1"
  local label="$2"
  if [[ "${RESP_STATUS}" != "${expected}" ]]; then
    print_response "${label}"
    die "${label}: expected HTTP ${expected}, got ${RESP_STATUS}"
  fi
}

json_field() {
  local field="$1"
  printf '%s' "${RESP_BODY}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('${field}',''))"
}

cmd_health() {
  require_cmd curl
  run_json_request "$(api_url /health)"
  print_response "GET /health"
  expect_status "200" "health"
}

cmd_upload() {
  require_cmd curl
  require_cmd python3
  local file_path="" encrypt="false"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -f|--file) file_path="${2:-}"; shift 2 ;;
      -e|--encrypt) encrypt="${2:-}"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) die "upload: unknown option '$1' (try --help)" ;;
    esac
  done

  [[ -n "${file_path}" ]] || die "upload: --file is required"
  [[ -f "${file_path}" ]] || die "upload: file not found: ${file_path}"
  case "${encrypt}" in
    true|false) ;;
    *) die "upload: --encrypt must be true or false" ;;
  esac

  local -a args=()
  build_curl_args args
  args+=(-w $'\nHTTP_STATUS:%{http_code}')
  args+=(-X POST)
  args+=(-F "file=@${file_path}")
  args+=(-F "encrypt=${encrypt}")
  args+=("$(api_url /api/v1/files)")

  local output
  output="$(curl "${args[@]}")"
  RESP_STATUS="$(printf '%s' "${output}" | awk -F: '/^HTTP_STATUS:/{print $2}' | tr -d '\r')"
  RESP_BODY="$(printf '%s' "${output}" | sed '/^HTTP_STATUS:/d')"

  print_response "POST /api/v1/files"
  expect_status "201" "upload"
  echo "FILE_ID=$(json_field id)"
}

cmd_list() {
  require_cmd curl
  local limit="20" offset="0"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -l|--limit) limit="${2:-}"; shift 2 ;;
      -o|--offset) offset="${2:-}"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) die "list: unknown option '$1' (try --help)" ;;
    esac
  done

  [[ "${limit}" =~ ^[0-9]+$ ]] || die "list: --limit must be an integer"
  [[ "${offset}" =~ ^[0-9]+$ ]] || die "list: --offset must be an integer"

  run_json_request "$(api_url /api/v1/files)?limit=${limit}&offset=${offset}"
  print_response "GET /api/v1/files?limit=${limit}&offset=${offset}"
  expect_status "200" "list"
}

cmd_download() {
  require_cmd curl
  local file_id="" out_path=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -i|--id) file_id="${2:-}"; shift 2 ;;
      -o|--out) out_path="${2:-}"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) die "download: unknown option '$1' (try --help)" ;;
    esac
  done

  [[ -n "${file_id}" ]] || die "download: --id is required"

  local url tmp_body status
  url="$(api_url "/api/v1/files/${file_id}/content")"
  tmp_body="$(mktemp)"

  local -a args=()
  build_curl_args args
  args+=(-o "${tmp_body}" -w "%{http_code}" "${url}")
  status="$(curl "${args[@]}")"
  RESP_STATUS="${status}"

  if [[ "${status}" != "200" ]]; then
    RESP_BODY="$(cat "${tmp_body}")"
    rm -f "${tmp_body}"
    print_response "GET /api/v1/files/{fileId}/content"
    die "download: expected HTTP 200, got ${status}"
  fi

  if [[ -z "${out_path}" ]]; then
    local -a head_args=()
    build_curl_args head_args
    local cd_header
    cd_header="$(curl -sSI "${head_args[@]}" "${url}" \
      | awk -F': ' 'tolower($1)=="content-disposition"{print $2}' \
      | tr -d '\r')"
    if [[ "${cd_header}" =~ filename=\"([^\"]+)\" ]]; then
      out_path="${BASH_REMATCH[1]}"
    else
      out_path="${file_id}.bin"
    fi
  fi

  mv "${tmp_body}" "${out_path}"
  echo "=== GET /api/v1/files/${file_id}/content ==="
  echo "HTTP ${status}"
  echo "Saved: ${out_path} ($(wc -c < "${out_path}" | tr -d ' ') bytes)"
}

cmd_delete() {
  require_cmd curl
  local file_id=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -i|--id) file_id="${2:-}"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) die "delete: unknown option '$1' (try --help)" ;;
    esac
  done

  [[ -n "${file_id}" ]] || die "delete: --id is required"

  local -a args=()
  build_curl_args args
  args+=(-w $'\nHTTP_STATUS:%{http_code}')
  args+=(-X DELETE)
  args+=("$(api_url "/api/v1/files/${file_id}")")

  local output
  output="$(curl "${args[@]}")"
  RESP_STATUS="$(printf '%s' "${output}" | awk -F: '/^HTTP_STATUS:/{print $2}' | tr -d '\r')"
  RESP_BODY="$(printf '%s' "${output}" | sed '/^HTTP_STATUS:/d')"

  print_response "DELETE /api/v1/files/${file_id}"
  expect_status "204" "delete"
}

cmd_all() {
  require_cmd curl
  require_cmd python3
  local file_path="" encrypt="false" keep=0

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -f|--file) file_path="${2:-}"; shift 2 ;;
      -e|--encrypt) encrypt="${2:-}"; shift 2 ;;
      -k|--keep) keep=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "all: unknown option '$1' (try --help)" ;;
    esac
  done

  local cleanup_sample=0
  if [[ -z "${file_path}" ]]; then
    file_path="$(mktemp)"
    printf 'smoke-test payload generated at %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${file_path}"
    cleanup_sample=1
  fi
  [[ -f "${file_path}" ]] || die "all: file not found: ${file_path}"
  case "${encrypt}" in
    true|false) ;;
    *) die "all: --encrypt must be true or false" ;;
  esac

  echo ">> health"
  cmd_health

  echo
  echo ">> upload (encrypt=${encrypt})"
  local -a upload_args=()
  build_curl_args upload_args
  upload_args+=(-w $'\nHTTP_STATUS:%{http_code}')
  upload_args+=(-X POST)
  upload_args+=(-F "file=@${file_path}")
  upload_args+=(-F "encrypt=${encrypt}")
  upload_args+=("$(api_url /api/v1/files)")

  local upload_out file_id
  upload_out="$(curl "${upload_args[@]}")"
  RESP_STATUS="$(printf '%s' "${upload_out}" | awk -F: '/^HTTP_STATUS:/{print $2}' | tr -d '\r')"
  RESP_BODY="$(printf '%s' "${upload_out}" | sed '/^HTTP_STATUS:/d')"
  print_response "POST /api/v1/files"
  expect_status "201" "upload"
  file_id="$(json_field id)"
  echo "FILE_ID=${file_id}"

  echo
  echo ">> list"
  cmd_list --limit 20 --offset 0

  echo
  echo ">> download"
  local download_path
  download_path="$(mktemp)"
  cmd_download --id "${file_id}" --out "${download_path}"
  if ! cmp -s "${file_path}" "${download_path}"; then
    rm -f "${download_path}"
    [[ "${cleanup_sample}" -eq 1 ]] && rm -f "${file_path}"
    die "downloaded content does not match uploaded file"
  fi
  echo "Content match: OK"
  rm -f "${download_path}"

  if [[ "${keep}" -eq 0 ]]; then
    echo
    echo ">> delete"
    cmd_delete --id "${file_id}"

    echo
    echo ">> download after delete (expect 404)"
    local status body_file
    body_file="$(mktemp)"
    local -a args=()
    build_curl_args args
    args+=(-o "${body_file}" -w "%{http_code}")
    args+=("$(api_url "/api/v1/files/${file_id}/content")")
    status="$(curl "${args[@]}")"
    echo "HTTP ${status}"
    python3 -m json.tool <"${body_file}" || cat "${body_file}"
    rm -f "${body_file}"
    [[ "${status}" == "404" ]] || die "expected 404 after delete, got ${status}"
  else
    echo
    echo "Keeping file ${file_id} (--keep)"
  fi

  [[ "${cleanup_sample}" -eq 1 ]] && rm -f "${file_path}"
  echo
  echo "All operations completed successfully."
}

# ---- main ----
while [[ $# -gt 0 ]]; do
  case "$1" in
    -u|--base-url) BASE_URL="${2:-}"; shift 2 ;;
    -r|--request-id) REQUEST_ID="${2:-}"; shift 2 ;;
    -v|--verbose) VERBOSE=1; shift ;;
    -h|--help|help)
      usage
      exit 0
      ;;
    --) shift; break ;;
    -*) die "unknown global option '$1' (try --help)" ;;
    *) break ;;
  esac
done

[[ $# -gt 0 ]] || { usage; exit 1; }

COMMAND="$1"
shift

case "${COMMAND}" in
  help|-h|--help) usage ;;
  health) cmd_health "$@" ;;
  upload) cmd_upload "$@" ;;
  list) cmd_list "$@" ;;
  download) cmd_download "$@" ;;
  delete) cmd_delete "$@" ;;
  all) cmd_all "$@" ;;
  *) die "unknown command '${COMMAND}' (try --help)" ;;
esac
