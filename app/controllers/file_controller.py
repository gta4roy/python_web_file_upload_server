"""Flask routes for file APIs (upload only in this iteration)."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.services.file_upload_service import FileUploadService
from app.utils.request_utils import (
    ensure_request_id,
    get_upload_file,
    parse_encrypt_flag,
    require_multipart,
)

files_bp = Blueprint("files", __name__)


@files_bp.before_app_request
def _assign_request_id() -> None:
    ensure_request_id()


@files_bp.after_app_request
def _attach_request_id_header(response):  # type: ignore[no-untyped-def]
    from flask import g

    request_id = getattr(g, "request_id", None)
    if request_id:
        response.headers["X-Request-Id"] = request_id
    return response


@files_bp.get("/")
def root():
    """Simple service info for browser checks (not part of the file API)."""
    return jsonify(
        {
            "service": "File Upload and Storage Server",
            "status": "ok",
            "upload": "POST /api/v1/files",
        }
    )


@files_bp.get("/health")
def health():
    """Liveness probe."""
    return jsonify({"status": "ok"})


@files_bp.post("/api/v1/files")
def upload_file():
    """POST /api/v1/files — upload a single file (OpenAPI uploadFile)."""
    require_multipart(request)
    upload = get_upload_file(request)
    encrypt = parse_encrypt_flag(request.form.get("encrypt"))

    service: FileUploadService = current_app.extensions["file_upload_service"]
    metadata = service.upload(upload, encrypt=encrypt)

    body = metadata.to_api_dict()
    response = jsonify(body)
    response.status_code = 201
    response.headers["Location"] = f"/api/v1/files/{metadata.id}"
    return response
