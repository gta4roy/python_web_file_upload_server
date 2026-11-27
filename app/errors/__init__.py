"""Application errors and handlers."""

from app.errors.error_handlers import AppError, register_error_handlers

__all__ = ["AppError", "register_error_handlers"]
