"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app
from app.config.settings import Settings


TEST_KEY_HEX = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


@pytest.fixture
def app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Configure isolated storage/metadata paths for each test."""
    storage = tmp_path / "files"
    temp = tmp_path / "temp"
    metadata = tmp_path / "file_metadata.json"
    storage.mkdir()
    temp.mkdir()

    monkeypatch.setenv("APP_HOST", "127.0.0.1")
    monkeypatch.setenv("APP_PORT", "5000")
    monkeypatch.setenv("APP_DEBUG", "false")
    monkeypatch.setenv("MAX_FILE_SIZE_MB", "1")
    monkeypatch.setenv("STORAGE_DIR", str(storage))
    monkeypatch.setenv("TEMP_DIR", str(temp))
    monkeypatch.setenv("METADATA_BACKEND", "json")
    monkeypatch.setenv("METADATA_FILE", str(metadata))
    monkeypatch.setenv("ENCRYPTION_ENABLED", "true")
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_KEY_HEX)

    return {
        "storage": storage,
        "temp": temp,
        "metadata": metadata,
    }


@pytest.fixture
def app(app_env):
    from app.config.settings import load_settings

    settings = load_settings()
    application = create_app(settings)
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def settings(app) -> Settings:
    return app.extensions["settings"]
