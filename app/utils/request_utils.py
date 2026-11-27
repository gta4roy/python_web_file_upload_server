"""HTTP request helpers."""

from __future__ import annotations

import uuid
from typing import Any

from flask import Request, g, request
from werkzeug.datastructures import FileStorage as WerkzeugFileStorage

from app.errors.error_handlers import AppError


def ensure_request_id() -> str:
    """Resolve or generate a request correlation ID and store it on ``g``."""
    incoming = request.headers.get("X-Request-Id", "").strip()
    if incoming:
        request_id = incoming[:128]
    else:
        request_id = f"req-{uuid.uuid4().hex[:8]}"
    g.request_id = request_id
    return request_id


def require_multipart(req: Request) -> None:
    """Reject requests that are not multipart/form-data."""
    content_type = (req.content_type or "").lower()
    if "multipart/form-data" not in content_type:
        raise AppError(
            "UNSUPPORTED_MEDIA_TYPE",
            "Request must use multipart/form-data for file upload.",
            415,
        )


def parse_encrypt_flag(raw: Any) -> bool:
    """Parse the optional ``encrypt`` form field (default false)."""
    if raw is None or raw == "":
        return False
    if isinstance(raw, bool):
        return raw
    value = str(raw).strip().lower()
    if value in {"true", "1", "yes", "on"}:
        return True
    if value in {"false", "0", "no", "off"}:
        return False
    raise AppError(
        "BAD_REQUEST",
        "Invalid encryption parameter. Expected a boolean value.",
        400,
    )


def get_upload_file(req: Request) -> WerkzeugFileStorage:
    """Extract and validate the uploaded ``file`` part."""
    if "file" not in req.files:
        raise AppError(
            "BAD_REQUEST",
            "Missing required file parameter.",
            400,
        )
    upload = req.files["file"]
    filename = (upload.filename or "").strip()
    if not filename:
        raise AppError(
            "BAD_REQUEST",
            "Uploaded filename must not be empty.",
            400,
        )
    return upload
