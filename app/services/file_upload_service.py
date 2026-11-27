"""Business logic for file uploads, listing, delete, and download."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from werkzeug.datastructures import FileStorage as WerkzeugFileStorage
from werkzeug.utils import secure_filename

from app.config.settings import Settings
from app.encryption.encryption_service import EncryptionService
from app.errors.error_handlers import AppError
from app.models.file_metadata import FileMetadata
from app.repositories.base_repository import MetadataRepository
from app.storage.file_storage import FileStorage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileDownload:
    """Payload needed to stream a download response."""

    metadata: FileMetadata
    # Unencrypted files are streamed from disk.
    path: Path | None = None
    # Encrypted files are decrypted to plaintext bytes (bounded by max size).
    content: bytes | None = None


class FileUploadService:
    """Orchestrate validation, storage, encryption, and metadata persistence."""

    def __init__(
        self,
        settings: Settings,
        storage: FileStorage,
        repository: MetadataRepository,
        encryption: EncryptionService,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.repository = repository
        self.encryption = encryption

    def upload(
        self,
        upload: WerkzeugFileStorage,
        *,
        encrypt: bool,
    ) -> FileMetadata:
        """Process an uploaded file and return persisted metadata."""
        original_filename = self._normalize_filename(upload.filename)
        content_type = upload.content_type or "application/octet-stream"

        if encrypt and not self.settings.encryption_enabled:
            raise AppError(
                "BAD_REQUEST",
                "Encryption is disabled on this server.",
                400,
            )

        file_id = str(uuid.uuid4())
        stored_filename = file_id
        temp_path: Path | None = None
        finalized = False

        try:
            stream = upload.stream
            if encrypt:
                temp_path, size_bytes = self.storage.write_stream_to_temp(
                    stream,
                    max_bytes=self.settings.max_file_size_bytes,
                    transform=self.encryption.encrypt,
                )
            else:
                temp_path, size_bytes = self.storage.write_stream_to_temp(
                    stream,
                    max_bytes=self.settings.max_file_size_bytes,
                )

            final_path = self.storage.finalize(temp_path, stored_filename)
            finalized = True
            temp_path = None

            metadata = FileMetadata(
                id=file_id,
                original_filename=original_filename,
                stored_filename=stored_filename,
                size_bytes=size_bytes,
                content_type=content_type,
                encrypted=encrypt,
                storage_path=str(final_path),
                uploaded_at=FileMetadata.utc_now_iso(),
            )

            try:
                self.repository.save(metadata)
            except Exception:
                # Roll back the stored file if metadata persistence fails.
                self.storage.delete_stored(stored_filename)
                raise

            logger.info(
                "Stored file id=%s encrypted=%s size=%s",
                file_id,
                encrypt,
                size_bytes,
            )
            return metadata
        except AppError:
            if temp_path is not None and not finalized:
                self.storage.safe_delete(temp_path)
            raise
        except OSError as exc:
            if temp_path is not None and not finalized:
                self.storage.safe_delete(temp_path)
            if getattr(exc, "errno", None) == 28:
                raise AppError(
                    "INSUFFICIENT_STORAGE",
                    "Insufficient storage capacity to complete the upload.",
                    507,
                    log_message=str(exc),
                ) from exc
            raise AppError(
                "INTERNAL_ERROR",
                "An unexpected error occurred while processing the request.",
                500,
                log_message=str(exc),
            ) from exc
        except Exception:
            if temp_path is not None and not finalized:
                self.storage.safe_delete(temp_path)
            raise

    def list_files(self, *, limit: int, offset: int) -> dict:
        """Return paginated public file metadata (OpenAPI FileListResponse)."""
        try:
            page, total = self.repository.list_files(limit=limit, offset=offset)
        except AppError:
            raise
        except Exception as exc:
            logger.exception("Failed to list files")
            raise AppError(
                "INTERNAL_ERROR",
                "An unexpected error occurred while processing the request.",
                500,
                log_message=str(exc),
            ) from exc

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "files": [item.to_api_dict() for item in page],
        }

    def delete_file(self, file_id: str) -> None:
        """Delete stored content and metadata for ``file_id``.

        Raises ``AppError`` with 404 when the file ID is unknown.
        Removes the physical file first, then metadata, so a successful
        response does not leave orphaned metadata for a deleted file.
        """
        try:
            metadata = self.repository.get_by_id(file_id)
        except AppError:
            raise
        except Exception as exc:
            logger.exception("Failed to load metadata for delete id=%s", file_id)
            raise AppError(
                "INTERNAL_ERROR",
                "An unexpected error occurred while processing the request.",
                500,
                log_message=str(exc),
            ) from exc

        if metadata is None:
            raise AppError(
                "FILE_NOT_FOUND",
                "The requested file does not exist.",
                404,
            )

        self.storage.delete_stored_strict(metadata.stored_filename)

        try:
            removed = self.repository.delete(file_id)
        except AppError:
            raise
        except Exception as exc:
            logger.exception(
                "Metadata delete failed after file removal id=%s", file_id
            )
            raise AppError(
                "INTERNAL_ERROR",
                "An unexpected error occurred while processing the request.",
                500,
                log_message=str(exc),
            ) from exc

        if not removed:
            # Race: another request deleted metadata after our get_by_id.
            raise AppError(
                "FILE_NOT_FOUND",
                "The requested file does not exist.",
                404,
            )

        logger.info("Deleted file id=%s", file_id)

    def get_download(self, file_id: str) -> FileDownload:
        """Load metadata and content for download (OpenAPI downloadFile)."""
        try:
            metadata = self.repository.get_by_id(file_id)
        except AppError:
            raise
        except Exception as exc:
            logger.exception("Failed to load metadata for download id=%s", file_id)
            raise AppError(
                "INTERNAL_ERROR",
                "An unexpected error occurred while processing the request.",
                500,
                log_message=str(exc),
            ) from exc

        if metadata is None:
            raise AppError(
                "FILE_NOT_FOUND",
                "The requested file does not exist.",
                404,
            )

        if metadata.encrypted:
            ciphertext = self.storage.read_stored(metadata.stored_filename)
            plaintext = self.encryption.decrypt(ciphertext)
            if len(plaintext) != metadata.size_bytes:
                logger.warning(
                    "Decrypted size mismatch id=%s expected=%s actual=%s",
                    file_id,
                    metadata.size_bytes,
                    len(plaintext),
                )
            return FileDownload(metadata=metadata, content=plaintext)

        path = self.storage.resolve_stored(metadata.stored_filename)
        return FileDownload(metadata=metadata, path=path)

    @staticmethod
    def _normalize_filename(filename: str | None) -> str:
        raw = (filename or "").strip()
        if not raw:
            raise AppError(
                "BAD_REQUEST",
                "Uploaded filename must not be empty.",
                400,
            )
        # Preserve a display name for metadata while neutralizing path segments.
        basename = Path(raw.replace("\\", "/")).name.strip()
        if not basename or basename in {".", ".."}:
            raise AppError(
                "BAD_REQUEST",
                "Uploaded filename must not be empty.",
                400,
            )
        # secure_filename may strip to empty for non-ASCII-only names; fall back.
        safe = secure_filename(basename)
        return safe or basename[:255]
