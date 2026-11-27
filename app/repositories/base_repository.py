"""Abstract metadata repository interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.file_metadata import FileMetadata


class MetadataRepository(ABC):
    """Replaceable persistence interface for file metadata."""

    @abstractmethod
    def save(self, metadata: FileMetadata) -> FileMetadata:
        """Persist a new metadata record. Must reject duplicate IDs."""

    @abstractmethod
    def list_files(self, limit: int, offset: int) -> tuple[list[FileMetadata], int]:
        """Return ``(page, total_count)`` for paginated listing."""

    @abstractmethod
    def get_by_id(self, file_id: str) -> FileMetadata | None:
        """Return metadata for ``file_id`` or ``None`` if missing."""

    @abstractmethod
    def delete(self, file_id: str) -> bool:
        """Delete metadata for ``file_id``. Return True if a record was removed."""
