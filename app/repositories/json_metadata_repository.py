"""JSON-file metadata repository with atomic writes and file locking."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path

from app.errors.error_handlers import AppError
from app.models.file_metadata import FileMetadata
from app.repositories.base_repository import MetadataRepository

logger = logging.getLogger(__name__)

try:
    import fcntl

    _HAS_FCNTL = True
except ImportError:  # pragma: no cover - Windows
    _HAS_FCNTL = False


class JsonFileMetadataRepository(MetadataRepository):
    """Persist metadata records in a single JSON file.

    On-disk format::

        {
          "files": {
            "<uuid>": { ... metadata fields ... }
          }
        }
    """

    def __init__(self, metadata_file: Path) -> None:
        self.metadata_file = metadata_file.resolve()
        self._thread_lock = threading.RLock()
        self._ensure_file()

    def save(self, metadata: FileMetadata) -> FileMetadata:
        with self._thread_lock:
            with self._locked_file() as handle:
                data = self._read_unlocked(handle)
                if metadata.id in data["files"]:
                    raise AppError(
                        "INTERNAL_ERROR",
                        "An unexpected error occurred while processing the request.",
                        500,
                        log_message=f"duplicate file id {metadata.id}",
                    )
                data["files"][metadata.id] = metadata.to_dict()
                self._atomic_write(data)
            return metadata

    def get_by_id(self, file_id: str) -> FileMetadata | None:
        with self._thread_lock:
            with self._locked_file() as handle:
                data = self._read_unlocked(handle)
                raw = data["files"].get(file_id)
                return FileMetadata.from_dict(raw) if raw else None

    def delete(self, file_id: str) -> bool:
        with self._thread_lock:
            with self._locked_file() as handle:
                data = self._read_unlocked(handle)
                if file_id not in data["files"]:
                    return False
                del data["files"][file_id]
                self._atomic_write(data)
                return True

    def list_files(self, limit: int, offset: int) -> tuple[list[FileMetadata], int]:
        with self._thread_lock:
            with self._locked_file() as handle:
                data = self._read_unlocked(handle)
                records = [
                    FileMetadata.from_dict(item)
                    for item in data["files"].values()
                ]
                records.sort(key=lambda item: item.uploaded_at, reverse=True)
                total = len(records)
                page = records[offset : offset + limit]
                return page, total

    def _ensure_file(self) -> None:
        self.metadata_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.metadata_file.exists():
            self._atomic_write({"files": {}})

    def _locked_file(self):
        return _FileLock(self.metadata_file)

    def _read_unlocked(self, handle) -> dict:
        handle.seek(0)
        content = handle.read()
        if not content.strip():
            return {"files": {}}
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AppError(
                "INTERNAL_ERROR",
                "An unexpected error occurred while processing the request.",
                500,
                log_message=f"corrupt metadata file: {exc}",
            ) from exc
        if not isinstance(data, dict) or "files" not in data:
            raise AppError(
                "INTERNAL_ERROR",
                "An unexpected error occurred while processing the request.",
                500,
                log_message="invalid metadata file structure",
            )
        if not isinstance(data["files"], dict):
            raise AppError(
                "INTERNAL_ERROR",
                "An unexpected error occurred while processing the request.",
                500,
                log_message="invalid metadata files map",
            )
        return data

    def _atomic_write(self, data: dict) -> None:
        self.metadata_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".metadata-",
            suffix=".tmp",
            dir=str(self.metadata_file.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                json.dump(data, tmp, indent=2, sort_keys=True)
                tmp.write("\n")
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, self.metadata_file)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise


class _FileLock:
    """Context manager providing exclusive flock around the metadata file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text('{"files": {}}\n', encoding="utf-8")
        self._handle = open(self.path, "r+", encoding="utf-8")
        if _HAS_FCNTL:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        return self._handle

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is not None:
            try:
                if _HAS_FCNTL:
                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._handle.close()
                self._handle = None
