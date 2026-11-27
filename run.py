#!/usr/bin/env python3
"""Development entrypoint for the file upload server."""

from __future__ import annotations

from app import create_app
from app.config.settings import load_settings


def main() -> None:
    settings = load_settings()
    app = create_app(settings)
    app.run(
        host=settings.app_host,
        port=settings.app_port,
        debug=settings.app_debug,
    )


if __name__ == "__main__":
    main()
