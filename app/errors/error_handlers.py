"""Centralized application errors and Flask error handlers."""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

logger = logging.getLogger(__name__)

_HTTP_CODE_MAP: dict[int, tuple[str, str]] = {
    400: ("BAD_REQUEST", "Invalid request."),
    404: ("FILE_NOT_FOUND", "The requested resource was not found."),
    405: ("BAD_REQUEST", "Method not allowed for this endpoint."),
    413: (
        "PAYLOAD_TOO_LARGE",
        "Uploaded file exceeds the maximum allowed size.",
    ),
    415: (
        "UNSUPPORTED_MEDIA_TYPE",
        "Request must use multipart/form-data for file upload.",
    ),
    507: (
        "INSUFFICIENT_STORAGE",
        "Insufficient storage capacity to complete the upload.",
    ),
}


class AppError(Exception):
    """Domain/application error mapped to a consistent API error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        *,
        log_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.log_message = log_message or message


def register_error_handlers(app: Flask) -> None:
    """Register handlers that emit OpenAPI ErrorResponse bodies."""

    @app.errorhandler(AppError)
    def handle_app_error(exc: AppError):  # type: ignore[no-untyped-def]
        logger.warning(
            "request_id=%s code=%s status=%s detail=%s",
            _request_id(),
            exc.code,
            exc.status_code,
            exc.log_message,
        )
        return _error_response(exc.code, exc.message, exc.status_code)

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_too_large(exc: RequestEntityTooLarge):  # type: ignore[no-untyped-def]
        logger.warning(
            "request_id=%s code=PAYLOAD_TOO_LARGE detail=%s",
            _request_id(),
            str(exc),
        )
        return _error_response(
            "PAYLOAD_TOO_LARGE",
            "Uploaded file exceeds the maximum allowed size.",
            413,
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc: HTTPException):  # type: ignore[no-untyped-def]
        status = int(exc.code or 500)
        api_code, default_message = _HTTP_CODE_MAP.get(
            status, ("INTERNAL_ERROR", "An unexpected error occurred while processing the request.")
        )
        message = default_message
        logger.info(
            "request_id=%s http_status=%s code=%s path_error=%s",
            _request_id(),
            status,
            api_code,
            exc.name,
        )
        return _error_response(api_code, message, status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):  # type: ignore[no-untyped-def]
        # HTTPException is a subclass of Exception; keep expected HTTP errors quiet.
        if isinstance(exc, HTTPException):
            return handle_http_exception(exc)
        logger.exception(
            "request_id=%s unexpected error: %s", _request_id(), exc
        )
        return _error_response(
            "INTERNAL_ERROR",
            "An unexpected error occurred while processing the request.",
            500,
        )


def _request_id() -> str:
    return getattr(g, "request_id", "unknown")


def _error_response(code: str, message: str, status: int) -> Any:
    body = {
        "code": code,
        "message": message,
        "requestId": _request_id(),
    }
    response = jsonify(body)
    response.status_code = status
    response.headers["X-Request-Id"] = _request_id()
    return response
