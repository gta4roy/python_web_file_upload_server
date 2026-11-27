"""Integration tests for POST /api/v1/files."""

from __future__ import annotations

import io
import json
import re
import uuid
from pathlib import Path

import pytest

from app import create_app
from app.config.settings import load_settings
from app.repositories.json_metadata_repository import JsonFileMetadataRepository


UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def test_upload_without_encryption(client, app_env):
    data = {
        "file": (io.BytesIO(b"hello world"), "report.txt"),
        "encrypt": "false",
    }
    response = client.post(
        "/api/v1/files",
        data=data,
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    body = response.get_json()
    assert UUID_RE.match(body["id"])
    assert body["name"] == "report.txt"
    assert body["size"] == len(b"hello world")
    assert body["contentType"].startswith("text/")
    assert body["encrypted"] is False
    assert "uploadedAt" in body
    assert "storage_path" not in body
    assert "storagePath" not in body
    assert response.headers["Location"] == f"/api/v1/files/{body['id']}"
    assert "X-Request-Id" in response.headers

    stored = app_env["storage"] / body["id"]
    assert stored.is_file()
    assert stored.read_bytes() == b"hello world"


def test_upload_with_encryption(client, app_env):
    payload = b"secret-bytes-123"
    response = client.post(
        "/api/v1/files",
        data={"file": (io.BytesIO(payload), "secret.bin"), "encrypt": "true"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    body = response.get_json()
    assert body["encrypted"] is True
    assert body["size"] == len(payload)
    assert "storage_path" not in body

    stored = app_env["storage"] / body["id"]
    assert stored.is_file()
    # Ciphertext must differ from plaintext and include nonce+tag overhead.
    assert stored.read_bytes() != payload
    assert len(stored.read_bytes()) == len(payload) + 12 + 16


def test_upload_missing_file_parameter(client):
    response = client.post(
        "/api/v1/files",
        data={"encrypt": "false"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["code"] == "BAD_REQUEST"
    assert "requestId" in body


def test_upload_empty_filename(client):
    response = client.post(
        "/api/v1/files",
        data={"file": (io.BytesIO(b"data"), "")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert response.get_json()["code"] == "BAD_REQUEST"


def test_upload_generates_uuid(client):
    response = client.post(
        "/api/v1/files",
        data={"file": (io.BytesIO(b"abc"), "a.txt")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    file_id = response.get_json()["id"]
    assert UUID_RE.match(file_id)
    uuid.UUID(file_id)


def test_upload_persists_metadata(client, app_env):
    response = client.post(
        "/api/v1/files",
        data={"file": (io.BytesIO(b"meta"), "meta.txt")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    file_id = response.get_json()["id"]

    raw = json.loads(app_env["metadata"].read_text(encoding="utf-8"))
    assert file_id in raw["files"]
    record = raw["files"][file_id]
    assert record["original_filename"] == "meta.txt"
    assert record["stored_filename"] == file_id
    assert "storage_path" in record


def test_response_hides_storage_path(client):
    response = client.post(
        "/api/v1/files",
        data={"file": (io.BytesIO(b"x"), "x.bin")},
        content_type="multipart/form-data",
    )
    body = response.get_json()
    dumped = json.dumps(body)
    assert "storage" not in dumped.lower() or "storage_path" not in dumped
    assert set(body.keys()) == {
        "id",
        "name",
        "size",
        "contentType",
        "encrypted",
        "uploadedAt",
    }


def test_failed_upload_leaves_no_incomplete_files(client, app_env, monkeypatch):
    repo = JsonFileMetadataRepository(app_env["metadata"])

    def boom(_metadata):
        raise RuntimeError("forced metadata failure")

    monkeypatch.setattr(repo, "save", boom)

    # Rebuild app with the patched repository.
    from app.config.settings import load_settings
    from app.encryption.encryption_service import EncryptionService
    from app.services.file_upload_service import FileUploadService
    from app.storage.file_storage import FileStorage

    settings = load_settings()
    app = create_app(settings)
    storage = FileStorage(settings.storage_dir, settings.temp_dir)
    encryption = EncryptionService(settings.encryption_enabled, settings.encryption_key)
    service = FileUploadService(settings, storage, repo, encryption)
    app.extensions["file_upload_service"] = service
    app.extensions["metadata_repository"] = repo

    test_client = app.test_client()
    before_files = set(app_env["storage"].iterdir())
    before_temp = set(app_env["temp"].iterdir())

    response = test_client.post(
        "/api/v1/files",
        data={"file": (io.BytesIO(b"will-fail"), "fail.txt")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 500

    assert set(app_env["storage"].iterdir()) == before_files
    # Temp files from the failed attempt should be cleaned up.
    assert set(app_env["temp"].iterdir()) == before_temp


def test_metadata_survives_restart(client, app_env):
    response = client.post(
        "/api/v1/files",
        data={"file": (io.BytesIO(b"persist-me"), "persist.txt")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    file_id = response.get_json()["id"]

    # Simulate restart by creating a new app/repository against the same file.
    settings = load_settings()
    restarted = create_app(settings)
    repo = restarted.extensions["metadata_repository"]
    loaded = repo.get_by_id(file_id)
    assert loaded is not None
    assert loaded.original_filename == "persist.txt"
    assert loaded.size_bytes == len(b"persist-me")


def test_unsupported_content_type(client):
    response = client.post(
        "/api/v1/files",
        data=b"not-multipart",
        content_type="application/json",
    )
    assert response.status_code == 415
    assert response.get_json()["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_invalid_encrypt_parameter(client):
    response = client.post(
        "/api/v1/files",
        data={"file": (io.BytesIO(b"x"), "x.txt"), "encrypt": "maybe"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert response.get_json()["code"] == "BAD_REQUEST"
