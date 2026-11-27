"""Integration tests for DELETE /api/v1/files/{fileId}."""

from __future__ import annotations

import io


def _upload(client, name: str = "report.txt", content: bytes = b"hello"):
    response = client.post(
        "/api/v1/files",
        data={"file": (io.BytesIO(content), name), "encrypt": "false"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    return response.get_json()


def test_delete_existing_file(client, app_env):
    uploaded = _upload(client)
    file_id = uploaded["id"]
    stored = app_env["storage"] / file_id
    assert stored.is_file()

    response = client.delete(f"/api/v1/files/{file_id}")
    assert response.status_code == 204
    assert response.data == b""
    assert "X-Request-Id" in response.headers
    assert not stored.exists()

    listing = client.get("/api/v1/files").get_json()
    assert listing["total"] == 0
    assert listing["files"] == []


def test_delete_missing_file_returns_404(client):
    response = client.delete(
        "/api/v1/files/a9e84e21-95d0-4c88-bcb2-52b99b4d8470"
    )
    assert response.status_code == 404
    body = response.get_json()
    assert body["code"] == "FILE_NOT_FOUND"
    assert "requestId" in body


def test_delete_invalid_uuid_returns_400(client):
    response = client.delete("/api/v1/files/not-a-uuid")
    assert response.status_code == 400
    assert response.get_json()["code"] == "BAD_REQUEST"


def test_delete_is_idempotent_after_success(client, app_env):
    uploaded = _upload(client, "once.txt", b"x")
    file_id = uploaded["id"]

    first = client.delete(f"/api/v1/files/{file_id}")
    assert first.status_code == 204

    second = client.delete(f"/api/v1/files/{file_id}")
    assert second.status_code == 404
    assert second.get_json()["code"] == "FILE_NOT_FOUND"


def test_delete_removes_metadata_when_disk_file_already_gone(client, app_env):
    uploaded = _upload(client, "ghost.txt", b"ghost")
    file_id = uploaded["id"]
    stored = app_env["storage"] / file_id
    stored.unlink()
    assert not stored.exists()

    response = client.delete(f"/api/v1/files/{file_id}")
    assert response.status_code == 204

    listing = client.get("/api/v1/files").get_json()
    assert listing["total"] == 0


def test_delete_encrypted_file(client, app_env):
    response = client.post(
        "/api/v1/files",
        data={"file": (io.BytesIO(b"secret"), "secret.bin"), "encrypt": "true"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    file_id = response.get_json()["id"]
    assert (app_env["storage"] / file_id).is_file()

    delete_response = client.delete(f"/api/v1/files/{file_id}")
    assert delete_response.status_code == 204
    assert not (app_env["storage"] / file_id).exists()
