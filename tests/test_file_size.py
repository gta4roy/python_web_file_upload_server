"""File size limit tests."""

from __future__ import annotations

import io


def test_upload_exceeds_configured_limit(client, settings):
    # MAX_FILE_SIZE_MB=1 in tests → 1 MiB limit
    oversized = b"a" * (settings.max_file_size_bytes + 1)
    response = client.post(
        "/api/v1/files",
        data={"file": (io.BytesIO(oversized), "big.bin")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 413
    body = response.get_json()
    assert body["code"] == "PAYLOAD_TOO_LARGE"
    assert "requestId" in body


def test_upload_at_exact_limit_succeeds(client, settings):
    exact = b"b" * settings.max_file_size_bytes
    response = client.post(
        "/api/v1/files",
        data={"file": (io.BytesIO(exact), "exact.bin")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    assert response.get_json()["size"] == settings.max_file_size_bytes
