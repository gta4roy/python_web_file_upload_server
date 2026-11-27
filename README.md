# File Upload and Storage Server

Python/Flask REST API implementing file APIs from the OpenAPI 3.1 specification in `openapi.yaml`:

- **POST `/api/v1/files`** — upload a file (optional AES-256-GCM encryption)
- **GET `/api/v1/files`** — list file metadata with `limit` / `offset` pagination
- **DELETE `/api/v1/files/{fileId}`** — delete file content and metadata
- **GET `/api/v1/files/{fileId}/content`** — download file bytes (decrypts when needed)

Content is stored on the filesystem; metadata uses a JSON file repository.

## Architecture

| Layer | Responsibility |
|---|---|
| `app/controllers` | HTTP validation and response mapping |
| `app/services` | Upload orchestration and consistency |
| `app/storage` | Temp files, streaming writes, atomic finalize |
| `app/repositories` | Replaceable metadata persistence (`json` now) |
| `app/encryption` | AES-256-GCM encrypt/decrypt helpers |
| `app/config` | Environment-driven settings |
| `app/models` | Internal metadata + public API mapping |
| `app/errors` | Consistent `{code,message,requestId}` errors |

Encrypted on-disk layout: `nonce (12) || ciphertext || tag (16)`.

## Prerequisites

- Python 3.12+
- `pip` / virtualenv

## Setup

```bash
cd python_web_file_upload_server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/.env.example config/.env
```

Generate a real encryption key for local use:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Place the value in `config/.env` as `ENCRYPTION_KEY`.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `APP_HOST` | `0.0.0.0` | Bind address |
| `APP_PORT` | `5000` | Bind port |
| `APP_DEBUG` | `false` | Flask debug mode |
| `MAX_FILE_SIZE_MB` | `100` | Max **file** size in MiB |
| `STORAGE_DIR` | `./storage/files` | Final file storage |
| `TEMP_DIR` | `./storage/temp` | Temporary upload/encrypt workspace |
| `METADATA_BACKEND` | `json` | Metadata backend (`json` only for now) |
| `METADATA_FILE` | `./data/file_metadata.json` | JSON metadata path |
| `ENCRYPTION_ENABLED` | `true` | Allow `encrypt=true` uploads |
| `ENCRYPTION_KEY` | _(required when enabled)_ | 32-byte key as 64 hex chars |

`MAX_CONTENT_LENGTH` is set to `MAX_FILE_SIZE_MB` plus a 1 MiB multipart overhead allowance. Application code still enforces the logical file-size limit.

If `ENCRYPTION_ENABLED=false`, requests with `encrypt=true` are rejected with HTTP 400 (they are not silently stored unencrypted).

## Run (development)

Uses `.venv` automatically:

```bash
./run.sh
```

## Run (production / Gunicorn)

Uses `.venv/bin/gunicorn`, writes `server.pid`, and logs under `logs/`:

```bash
./start_server.sh
./stop_server.sh
```

## Upload examples

Without encryption:

```bash
curl -X POST http://localhost:5000/api/v1/files \
  -F "file=@report.pdf" \
  -F "encrypt=false"
```

With encryption:

```bash
curl -X POST http://localhost:5000/api/v1/files \
  -F "file=@report.pdf" \
  -F "encrypt=true"
```

List files (paginated):

```bash
curl "http://localhost:5000/api/v1/files?limit=20&offset=0"
```

Delete a file:

```bash
curl -X DELETE http://localhost:5000/api/v1/files/<file-id>
```

Download a file:

```bash
curl -OJ http://localhost:5000/api/v1/files/<file-id>/content
```

### Example `201` response

```json
{
  "id": "a9e84e21-95d0-4c88-bcb2-52b99b4d8470",
  "name": "report.pdf",
  "size": 1048576,
  "contentType": "application/pdf",
  "encrypted": true,
  "uploadedAt": "2026-11-27T12:30:00Z"
}
```

Headers include `Location: /api/v1/files/{id}` and `X-Request-Id`.

### Example `200` list response

```json
{
  "total": 1,
  "limit": 20,
  "offset": 0,
  "files": [
    {
      "id": "a9e84e21-95d0-4c88-bcb2-52b99b4d8470",
      "name": "report.pdf",
      "size": 1048576,
      "contentType": "application/pdf",
      "encrypted": true,
      "uploadedAt": "2026-11-27T12:30:00Z"
    }
  ]
}
```

## Storage layout

```text
storage/
  files/          # UUID-named finalized files
  temp/           # transient upload/encrypt workspace
data/
  file_metadata.json
```

Physical filenames are UUIDs only. Original names are metadata.

## Tests

Unit/integration:

```bash
pytest -q
```

Manual API smoke script against a running server (`openapi.yaml` operations):

```bash
./test_api.sh help
./start_server.sh
./test_api.sh all --file ./README.md --encrypt true
./test_api.sh list --limit 10 --offset 0
./stop_server.sh
```

### Grafana k6 load test

Each iteration: **upload → list → download → delete**. The runner generates a random file of the requested size.

```bash
./start_server.sh
./run_load_test.sh --help
./run_load_test.sh 5 50 64K
./run_load_test.sh --users 10 --iterations 100 --file-size 1M --encrypt false
./stop_server.sh
```

Requires [k6](https://grafana.com/docs/k6/latest/set-up/install-k6/) on `PATH`.

## OpenAPI contract

The public response and error shapes follow `openapi.yaml`:

- Success body: `id`, `name`, `size`, `contentType`, `encrypted`, `uploadedAt`
- Errors: `code`, `message`, `requestId`
- Size overflow uses `PAYLOAD_TOO_LARGE` (HTTP 413)
