"""Business logic for file uploads."""

from __future__ import annotations

import logging
import uuid
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
