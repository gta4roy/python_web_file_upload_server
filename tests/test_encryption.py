"""Encryption module and encryption-related upload behavior."""

from __future__ import annotations

import io

import pytest

from app import create_app
from app.config.settings import load_settings
from app.encryption.encryption_service import EncryptionService


TEST_KEY = bytes.fromhex(
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
)


def test_encrypt_decrypt_roundtrip():
    service = EncryptionService(enabled=True, key=TEST_KEY)
    plaintext = b"roundtrip-data"
    payload = service.encrypt(plaintext)
    assert payload != plaintext
    assert service.decrypt(payload) == plaintext


def test_encryption_disabled_rejects_encrypt_request(app_env, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_ENABLED", "false")
    # Key may still be present; encryption should still be rejected.
    settings = load_settings()
    app = create_app(settings)
    client = app.test_client()

    response = client.post(
        "/api/v1/files",
        data={"file": (io.BytesIO(b"plain"), "a.txt"), "encrypt": "true"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert response.get_json()["code"] == "BAD_REQUEST"


def test_encryption_disabled_allows_plain_upload(app_env, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_ENABLED", "false")
    settings = load_settings()
    app = create_app(settings)
    client = app.test_client()

    response = client.post(
        "/api/v1/files",
        data={"file": (io.BytesIO(b"plain"), "a.txt"), "encrypt": "false"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    assert response.get_json()["encrypted"] is False


def test_missing_key_when_encryption_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("ENCRYPTION_ENABLED", "true")
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "files"))
    monkeypatch.setenv("TEMP_DIR", str(tmp_path / "temp"))
    monkeypatch.setenv("METADATA_FILE", str(tmp_path / "meta.json"))
    # Avoid reloading secrets from config/.env during this negative test.
    with pytest.raises(ValueError, match="ENCRYPTION_KEY"):
        load_settings(env_file=tmp_path / "missing.env")
