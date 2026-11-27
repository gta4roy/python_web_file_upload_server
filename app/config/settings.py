"""Centralized configuration loaded from environment variables / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Multipart encoding overhead allowance on top of MAX_FILE_SIZE_MB.
_REQUEST_OVERHEAD_BYTES = 1 * 1024 * 1024  # 1 MiB


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings for the upload server."""

    app_host: str
    app_port: int
    app_debug: bool
    max_file_size_mb: int
    max_file_size_bytes: int
    max_request_size_bytes: int
    storage_dir: Path
    temp_dir: Path
    metadata_backend: str
    metadata_file: Path
    encryption_enabled: bool
    encryption_key: bytes | None


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load and validate settings from the environment.

    Looks for ``config/.env`` by default when present. Explicit ``env_file``
    overrides that path. Existing process environment variables win.
    """
    if env_file is not None:
        load_dotenv(env_file, override=False)
    else:
        default_env = Path("config/.env")
        if default_env.is_file():
            load_dotenv(default_env, override=False)
        example_env = Path("config/.env.example")
        # Do not auto-load example secrets in production; tests may set env.

    app_host = os.getenv("APP_HOST", "0.0.0.0")
    app_port = _parse_int("APP_PORT", os.getenv("APP_PORT", "5000"), minimum=1)
    app_debug = _parse_bool(os.getenv("APP_DEBUG", "false"))

    max_file_size_mb = _parse_int(
        "MAX_FILE_SIZE_MB", os.getenv("MAX_FILE_SIZE_MB", "100"), minimum=1
    )
    max_file_size_bytes = max_file_size_mb * 1024 * 1024
    max_request_size_bytes = max_file_size_bytes + _REQUEST_OVERHEAD_BYTES

    storage_dir = Path(os.getenv("STORAGE_DIR", "./storage/files")).resolve()
    temp_dir = Path(os.getenv("TEMP_DIR", "./storage/temp")).resolve()
    metadata_backend = os.getenv("METADATA_BACKEND", "json").strip().lower()
    metadata_file = Path(
        os.getenv("METADATA_FILE", "./data/file_metadata.json")
    ).resolve()

    encryption_enabled = _parse_bool(os.getenv("ENCRYPTION_ENABLED", "true"))
    encryption_key = _parse_encryption_key(
        os.getenv("ENCRYPTION_KEY"),
        required=encryption_enabled,
    )

    if metadata_backend not in {"json"}:
        raise ValueError(
            f"Invalid METADATA_BACKEND '{metadata_backend}'. Supported: json"
        )

    return Settings(
        app_host=app_host,
        app_port=app_port,
        app_debug=app_debug,
        max_file_size_mb=max_file_size_mb,
        max_file_size_bytes=max_file_size_bytes,
        max_request_size_bytes=max_request_size_bytes,
        storage_dir=storage_dir,
        temp_dir=temp_dir,
        metadata_backend=metadata_backend,
        metadata_file=metadata_file,
        encryption_enabled=encryption_enabled,
        encryption_key=encryption_key,
    )


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean configuration value: {value!r}")


def _parse_int(name: str, value: str, *, minimum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid integer for {name}: {value!r}") from exc
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {parsed}")
    return parsed


def _parse_encryption_key(raw: str | None, *, required: bool) -> bytes | None:
    if not required:
        if not raw:
            return None
        # Still validate if provided so misconfiguration is caught early.
    if not raw:
        raise ValueError(
            "ENCRYPTION_KEY is required when ENCRYPTION_ENABLED=true "
            "(64 hex characters representing 32 bytes)"
        )
    key_hex = raw.strip()
    try:
        key = bytes.fromhex(key_hex)
    except ValueError as exc:
        raise ValueError(
            "ENCRYPTION_KEY must be a valid hex-encoded string"
        ) from exc
    if len(key) != 32:
        raise ValueError(
            f"ENCRYPTION_KEY must decode to 32 bytes (AES-256), got {len(key)}"
        )
    return key
