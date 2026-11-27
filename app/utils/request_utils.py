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


def parse_file_id(raw: str | None) -> str:
    """Validate a path ``fileId`` as a UUID and return the canonical string."""
    value = (raw or "").strip()
    if not value:
        raise AppError(
            "BAD_REQUEST",
            "Invalid file ID. Expected a UUID.",
            400,
        )
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError) as exc:
        raise AppError(
            "BAD_REQUEST",
            "Invalid file ID. Expected a UUID.",
            400,
        ) from exc


def parse_pagination_params(
    req: Request,
    *,
    default_limit: int = 20,
    max_limit: int = 100,
) -> tuple[int, int]:
    """Parse OpenAPI ``limit`` / ``offset`` query parameters.

    Returns ``(limit, offset)`` with defaults ``20`` / ``0``.
    """
    limit = _parse_non_negative_int(
        req.args.get("limit"),
        field_name="limit",
        default=default_limit,
        minimum=1,
        maximum=max_limit,
    )
    offset = _parse_non_negative_int(
        req.args.get("offset"),
        field_name="offset",
        default=0,
        minimum=0,
        maximum=None,
    )
    return limit, offset


def _parse_non_negative_int(
    raw: Any,
    *,
    field_name: str,
    default: int,
    minimum: int,
    maximum: int | None,
) -> int:
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise AppError(
            "BAD_REQUEST",
            f"Invalid {field_name} parameter. Expected an integer.",
            400,
        ) from exc
    if value < minimum:
        raise AppError(
            "BAD_REQUEST",
            f"Invalid {field_name} parameter. Must be >= {minimum}.",
            400,
        )
    if maximum is not None and value > maximum:
        raise AppError(
            "BAD_REQUEST",
            f"Invalid {field_name} parameter. Must be <= {maximum}.",
            400,
        )
    return value
