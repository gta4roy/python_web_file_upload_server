"""File metadata domain model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class FileMetadata:
    """Internal metadata record for a stored file."""

    id: str
    original_filename: str
    stored_filename: str
    size_bytes: int
    content_type: str
    encrypted: bool
    storage_path: str
    uploaded_at: str

    @staticmethod
    def utc_now_iso() -> str:
        """Return current UTC timestamp in ISO-8601 with Z suffix."""
        return (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full internal record (including storage_path)."""
        return asdict(self)

    def to_api_dict(self) -> dict[str, Any]:
        """Public API representation matching OpenAPI FileMetadata schema."""
        return {
            "id": self.id,
            "name": self.original_filename,
            "size": self.size_bytes,
            "contentType": self.content_type,
            "encrypted": self.encrypted,
            "uploadedAt": self.uploaded_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileMetadata:
        """Deserialize a metadata record from storage."""
        return cls(
            id=str(data["id"]),
            original_filename=str(data["original_filename"]),
            stored_filename=str(data["stored_filename"]),
            size_bytes=int(data["size_bytes"]),
            content_type=str(data["content_type"]),
            encrypted=bool(data["encrypted"]),
            storage_path=str(data["storage_path"]),
            uploaded_at=str(data["uploaded_at"]),
        )
