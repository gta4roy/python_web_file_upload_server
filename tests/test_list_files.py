"""Integration tests for GET /api/v1/files."""

from __future__ import annotations

import io


def _upload(client, name: str, content: bytes = b"data", encrypt: str = "false"):
    response = client.post(
        "/api/v1/files",
        data={"file": (io.BytesIO(content), name), "encrypt": encrypt},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    return response.get_json()


def test_list_empty(client):
    response = client.get("/api/v1/files")
    assert response.status_code == 200
    body = response.get_json()
    assert body == {"total": 0, "limit": 20, "offset": 0, "files": []}
    assert "X-Request-Id" in response.headers


def test_list_returns_metadata_only(client):
    uploaded = _upload(client, "report.txt", b"hello")
    response = client.get("/api/v1/files")
    assert response.status_code == 200
    body = response.get_json()
    assert body["total"] == 1
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert len(body["files"]) == 1
    item = body["files"][0]
    assert item["id"] == uploaded["id"]
    assert item["name"] == "report.txt"
    assert item["size"] == 5
    assert item["encrypted"] is False
    assert set(item.keys()) == {
        "id",
        "name",
        "size",
        "contentType",
        "encrypted",
        "uploadedAt",
    }
    assert "storage_path" not in item
    assert "storagePath" not in item
    assert "stored_filename" not in item


def test_list_pagination(client, monkeypatch):
    stamps = iter(
        [
            "2026-11-27T12:30:00Z",
            "2026-11-27T12:31:00Z",
            "2026-11-27T12:32:00Z",
        ]
    )
    monkeypatch.setattr(
        "app.services.file_upload_service.FileMetadata.utc_now_iso",
        lambda: next(stamps),
    )

    first = _upload(client, "a.txt", b"a")
    second = _upload(client, "b.txt", b"b")
    third = _upload(client, "c.txt", b"c")

    page1 = client.get("/api/v1/files?limit=2&offset=0").get_json()
    assert page1["total"] == 3
    assert page1["limit"] == 2
    assert page1["offset"] == 0
    assert len(page1["files"]) == 2
    # Newest first
    assert page1["files"][0]["id"] == third["id"]
    assert page1["files"][1]["id"] == second["id"]

    page2 = client.get("/api/v1/files?limit=2&offset=2").get_json()
    assert page2["total"] == 3
    assert page2["limit"] == 2
    assert page2["offset"] == 2
    assert len(page2["files"]) == 1
    assert page2["files"][0]["id"] == first["id"]


def test_list_default_pagination_params(client):
    _upload(client, "one.txt")
    body = client.get("/api/v1/files").get_json()
    assert body["limit"] == 20
    assert body["offset"] == 0


def test_list_invalid_limit(client):
    response = client.get("/api/v1/files?limit=0")
    assert response.status_code == 400
    assert response.get_json()["code"] == "BAD_REQUEST"

    response = client.get("/api/v1/files?limit=101")
    assert response.status_code == 400
    assert response.get_json()["code"] == "BAD_REQUEST"

    response = client.get("/api/v1/files?limit=abc")
    assert response.status_code == 400
    assert response.get_json()["code"] == "BAD_REQUEST"


def test_list_invalid_offset(client):
    response = client.get("/api/v1/files?offset=-1")
    assert response.status_code == 400
    assert response.get_json()["code"] == "BAD_REQUEST"

    response = client.get("/api/v1/files?offset=nope")
    assert response.status_code == 400
    assert response.get_json()["code"] == "BAD_REQUEST"


def test_list_offset_beyond_total(client):
    _upload(client, "only.txt")
    body = client.get("/api/v1/files?limit=10&offset=50").get_json()
    assert body["total"] == 1
    assert body["offset"] == 50
    assert body["files"] == []
