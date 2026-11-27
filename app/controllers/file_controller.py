"""Flask routes for file APIs."""

from __future__ import annotations

from io import BytesIO

from flask import Blueprint, current_app, jsonify, request, send_file

from app.services.file_upload_service import FileUploadService
from app.utils.request_utils import (
    ensure_request_id,
    get_upload_file,
    parse_encrypt_flag,
    parse_file_id,
    parse_pagination_params,
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
            "endpoints": {
                "upload": "POST /api/v1/files",
                "list": "GET /api/v1/files",
                "delete": "DELETE /api/v1/files/{fileId}",
                "download": "GET /api/v1/files/{fileId}/content",
            },
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


@files_bp.get("/api/v1/files")
def list_files():
    """GET /api/v1/files — list uploaded file metadata (OpenAPI listFiles)."""
    limit, offset = parse_pagination_params(request)
    service: FileUploadService = current_app.extensions["file_upload_service"]
    body = service.list_files(limit=limit, offset=offset)
    return jsonify(body), 200


@files_bp.delete("/api/v1/files/<file_id>")
def delete_file(file_id: str):
    """DELETE /api/v1/files/{fileId} — delete file + metadata (OpenAPI deleteFile)."""
    validated_id = parse_file_id(file_id)
    service: FileUploadService = current_app.extensions["file_upload_service"]
    service.delete_file(validated_id)
    return ("", 204)


@files_bp.get("/api/v1/files/<file_id>/content")
def download_file(file_id: str):
    """GET /api/v1/files/{fileId}/content — download file bytes (OpenAPI downloadFile)."""
    validated_id = parse_file_id(file_id)
    service: FileUploadService = current_app.extensions["file_upload_service"]
    download = service.get_download(validated_id)
    metadata = download.metadata

    if download.path is not None:
        response = send_file(
            download.path,
            mimetype=metadata.content_type,
            as_attachment=True,
            download_name=metadata.original_filename,
            conditional=True,
        )
    else:
        assert download.content is not None
        buffer = BytesIO(download.content)
        response = send_file(
            buffer,
            mimetype=metadata.content_type,
            as_attachment=True,
            download_name=metadata.original_filename,
            max_age=0,
        )

    response.headers["Content-Length"] = str(metadata.size_bytes)
    # Ensure disposition uses the original filename even if send_file encodes it.
    safe_name = metadata.original_filename.replace("\\", "\\\\").replace('"', '\\"')
    response.headers["Content-Disposition"] = f'attachment; filename="{safe_name}"'
    return response
