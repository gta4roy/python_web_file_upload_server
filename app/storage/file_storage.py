"""Filesystem storage for uploaded files with atomic finalize."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import BinaryIO, Callable
from uuid import uuid4

from app.errors.error_handlers import AppError

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024  # 1 MiB


class FileStorage:
    """Manage temporary and final file storage under configured directories."""

    def __init__(self, storage_dir: Path, temp_dir: Path) -> None:
        self.storage_dir = storage_dir.resolve()
        self.temp_dir = temp_dir.resolve()

    def ensure_directories(self) -> None:
        """Create storage and temp directories when missing."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def create_temp_path(self, prefix: str = "upload-") -> Path:
        """Allocate a unique temporary path under TEMP_DIR."""
        self.ensure_directories()
        return self.temp_dir / f"{prefix}{uuid4().hex}"

    def final_path_for(self, stored_filename: str) -> Path:
        """Resolve the final storage path for a server-generated filename."""
        if not stored_filename or "/" in stored_filename or "\\" in stored_filename:
            raise AppError(
                "BAD_REQUEST",
                "Invalid stored filename.",
                400,
            )
        if stored_filename in {".", ".."} or ".." in stored_filename:
            raise AppError(
                "BAD_REQUEST",
                "Invalid stored filename.",
                400,
            )
        path = (self.storage_dir / stored_filename).resolve()
        if path.parent != self.storage_dir:
            raise AppError(
                "BAD_REQUEST",
                "Invalid stored filename.",
                400,
            )
        return path

    def write_stream_to_temp(
        self,
        source: BinaryIO,
        *,
        max_bytes: int,
        transform: Callable[[bytes], bytes] | None = None,
    ) -> tuple[Path, int]:
        """Stream ``source`` into a temp file, enforcing ``max_bytes``.

        Returns ``(temp_path, bytes_written_from_source)``.
        ``transform``, when provided, receives the full plaintext and must
        return ciphertext to write (used for AES-GCM within size limits).
        """
        temp_path = self.create_temp_path()
        bytes_read = 0
        try:
            if transform is None:
                with temp_path.open("wb") as out:
                    while True:
                        chunk = source.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        bytes_read += len(chunk)
                        if bytes_read > max_bytes:
                            raise AppError(
                                "PAYLOAD_TOO_LARGE",
                                "Uploaded file exceeds the maximum allowed size.",
                                413,
                            )
                        out.write(chunk)
            else:
                # Whole-file transform within the configured max size limit.
                chunks: list[bytes] = []
                while True:
                    chunk = source.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    bytes_read += len(chunk)
                    if bytes_read > max_bytes:
                        raise AppError(
                            "PAYLOAD_TOO_LARGE",
                            "Uploaded file exceeds the maximum allowed size.",
                            413,
                        )
                    chunks.append(chunk)
                plaintext = b"".join(chunks)
                ciphertext = transform(plaintext)
                with temp_path.open("wb") as out:
                    out.write(ciphertext)
            return temp_path, bytes_read
        except AppError:
            self.safe_delete(temp_path)
            raise
        except OSError as exc:
            self.safe_delete(temp_path)
            if getattr(exc, "errno", None) == 28:  # ENOSPC
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

    def finalize(self, temp_path: Path, stored_filename: str) -> Path:
        """Atomically move a completed temp file into the storage directory."""
        final_path = self.final_path_for(stored_filename)
        try:
            os.replace(temp_path, final_path)
            return final_path
        except OSError as exc:
            self.safe_delete(temp_path)
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

    def safe_delete(self, path: Path | None) -> None:
        """Best-effort delete that never raises to callers."""
        if path is None:
            return
        try:
            if path.is_file():
                path.unlink()
        except OSError as exc:
            logger.warning("Failed to delete path %s: %s", path, exc)

    def delete_stored(self, stored_filename: str) -> None:
        """Delete a finalized stored file if present."""
        try:
            path = self.final_path_for(stored_filename)
        except AppError:
            return
        self.safe_delete(path)

    def copy_to_temp(self, source_path: Path) -> Path:
        """Copy an existing file into a new temp path (test helper)."""
        dest = self.create_temp_path()
        shutil.copy2(source_path, dest)
        return dest
