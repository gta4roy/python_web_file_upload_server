"""Unit tests for JsonFileMetadataRepository."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.errors.error_handlers import AppError
from app.models.file_metadata import FileMetadata
from app.repositories.json_metadata_repository import JsonFileMetadataRepository


def _sample(file_id: str = "a9e84e21-95d0-4c88-bcb2-52b99b4d8470") -> FileMetadata:
    return FileMetadata(
        id=file_id,
        original_filename="report.pdf",
        stored_filename=file_id,
        size_bytes=100,
        content_type="application/pdf",
        encrypted=False,
        storage_path=f"/tmp/{file_id}",
        uploaded_at="2026-11-27T12:30:00Z",
    )


def test_save_and_get(tmp_path: Path):
    path = tmp_path / "meta.json"
    repo = JsonFileMetadataRepository(path)
    saved = repo.save(_sample())
    loaded = repo.get_by_id(saved.id)
    assert loaded is not None
    assert loaded.original_filename == "report.pdf"
    assert path.is_file()


def test_rejects_duplicate_ids(tmp_path: Path):
    repo = JsonFileMetadataRepository(tmp_path / "meta.json")
    repo.save(_sample())
    with pytest.raises(AppError) as exc:
        repo.save(_sample())
    assert exc.value.status_code == 500


def test_list_and_delete(tmp_path: Path):
    repo = JsonFileMetadataRepository(tmp_path / "meta.json")
    first = _sample("11111111-1111-4111-8111-111111111111")
    second = _sample("22222222-2222-4222-8222-222222222222")
    second.uploaded_at = "2026-11-27T13:00:00Z"
    repo.save(first)
    repo.save(second)

    page, total = repo.list_files(limit=1, offset=0)
    assert total == 2
    assert len(page) == 1
    assert page[0].id == second.id

    assert repo.delete(first.id) is True
    assert repo.get_by_id(first.id) is None
    assert repo.delete(first.id) is False


def test_creates_file_automatically(tmp_path: Path):
    path = tmp_path / "nested" / "meta.json"
    repo = JsonFileMetadataRepository(path)
    assert path.is_file()
    assert repo.list_files(10, 0)[1] == 0
