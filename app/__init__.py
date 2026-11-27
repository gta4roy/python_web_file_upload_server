"""Flask application factory for the file upload server."""

from __future__ import annotations

import logging

from flask import Flask

from app.config.settings import Settings, load_settings
from app.encryption.encryption_service import EncryptionService
from app.errors.error_handlers import register_error_handlers
from app.repositories.base_repository import MetadataRepository
from app.repositories.json_metadata_repository import JsonFileMetadataRepository
from app.services.file_upload_service import FileUploadService
from app.storage.file_storage import FileStorage


def create_app(settings: Settings | None = None) -> Flask:
    """Create and configure the Flask application."""
    cfg = settings or load_settings()

    app = Flask(__name__)
    app.config["SETTINGS"] = cfg
    # Allow multipart overhead above the logical file size limit.
    app.config["MAX_CONTENT_LENGTH"] = cfg.max_request_size_bytes

    _configure_logging(app, cfg)

    storage = FileStorage(storage_dir=cfg.storage_dir, temp_dir=cfg.temp_dir)
    storage.ensure_directories()

    repository = _build_repository(cfg)
    encryption = EncryptionService(
        enabled=cfg.encryption_enabled,
        key=cfg.encryption_key,
    )
    upload_service = FileUploadService(
        settings=cfg,
        storage=storage,
        repository=repository,
        encryption=encryption,
    )

    app.extensions["settings"] = cfg
    app.extensions["file_storage"] = storage
    app.extensions["metadata_repository"] = repository
    app.extensions["encryption_service"] = encryption
    app.extensions["file_upload_service"] = upload_service

    from app.controllers.file_controller import files_bp

    app.register_blueprint(files_bp)
    register_error_handlers(app)

    return app


def _build_repository(cfg: Settings) -> MetadataRepository:
    backend = cfg.metadata_backend.lower()
    if backend == "json":
        return JsonFileMetadataRepository(cfg.metadata_file)
    raise ValueError(
        f"Unsupported METADATA_BACKEND '{cfg.metadata_backend}'. Supported: json"
    )


def _configure_logging(app: Flask, cfg: Settings) -> None:
    level = logging.DEBUG if cfg.app_debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    app.logger.setLevel(level)
