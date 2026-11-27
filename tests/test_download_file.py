"""Integration tests for GET /api/v1/files/{fileId}/content."""

from __future__ import annotations

import io


def _upload(client, name: str, content: bytes, encrypt: str = "false"):
    response = client.post(
        "/api/v1/files",
        data={"file": (io.BytesIO(content), name), "encrypt": encrypt},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    return response.get_json()


def test_download_unencrypted_file(client):
    payload = b"hello download world"
    uploaded = _upload(client, "report.txt", payload, encrypt="false")

    response = client.get(f"/api/v1/files/{uploaded['id']}/content")
    assert response.status_code == 200
    assert response.data == payload
    assert response.headers["Content-Type"].startswith("text/")
    assert 'attachment; filename="report.txt"' in response.headers["Content-Disposition"]
    assert response.headers["Content-Length"] == str(len(payload))
    assert "X-Request-Id" in response.headers


def test_download_encrypted_file_returns_plaintext(client, app_env):
    payload = b"top-secret-bytes"
    uploaded = _upload(client, "secret.bin", payload, encrypt="true")

    # Ciphertext on disk must differ from plaintext.
    stored = (app_env["storage"] / uploaded["id"]).read_bytes()
    assert stored != payload

    response = client.get(f"/api/v1/files/{uploaded['id']}/content")
    assert response.status_code == 200
    assert response.data == payload
    assert response.headers["Content-Length"] == str(len(payload))
    assert 'filename="secret.bin"' in response.headers["Content-Disposition"]


def test_download_missing_file_returns_404(client):
    response = client.get(
        "/api/v1/files/a9e84e21-95d0-4c88-bcb2-52b99b4d8470/content"
    )
    assert response.status_code == 404
    body = response.get_json()
    assert body["code"] == "FILE_NOT_FOUND"
    assert "requestId" in body


def test_download_invalid_uuid_returns_400(client):
    response = client.get("/api/v1/files/not-a-uuid/content")
    assert response.status_code == 400
    assert response.get_json()["code"] == "BAD_REQUEST"


def test_download_missing_disk_file_returns_404(client, app_env):
    uploaded = _upload(client, "gone.txt", b"gone")
    (app_env["storage"] / uploaded["id"]).unlink()

    response = client.get(f"/api/v1/files/{uploaded['id']}/content")
    assert response.status_code == 404
    assert response.get_json()["code"] == "FILE_NOT_FOUND"


def test_download_decryption_failure(client, app_env):
    uploaded = _upload(client, "broken.bin", b"cipher-me", encrypt="true")
    path = app_env["storage"] / uploaded["id"]
    # Corrupt ciphertext while keeping length plausible.
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 0xFF
    path.write_bytes(bytes(raw))

    response = client.get(f"/api/v1/files/{uploaded['id']}/content")
    assert response.status_code == 500
    body = response.get_json()
    assert body["code"] == "DECRYPTION_FAILED"
    assert "key" not in body["message"].lower()
    assert "nonce" not in body["message"].lower()


def test_download_after_delete_returns_404(client):
    uploaded = _upload(client, "temp.txt", b"temp")
    assert client.delete(f"/api/v1/files/{uploaded['id']}").status_code == 204
    response = client.get(f"/api/v1/files/{uploaded['id']}/content")
    assert response.status_code == 404
