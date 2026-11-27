"""AES-256-GCM encryption helpers.

Encrypted file layout (documented, non-custom algorithm):
    nonce (12 bytes) || ciphertext || tag (16 bytes)

Encryption is applied to the complete plaintext within the configured maximum
file size. This avoids inventing a custom chunked AEAD protocol while remaining
safe under the MAX_FILE_SIZE_MB limit.
"""

from __future__ import annotations

import logging

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

from app.errors.error_handlers import AppError

logger = logging.getLogger(__name__)

NONCE_SIZE = 12
TAG_SIZE = 16


class EncryptionService:
    """Optional AES-256-GCM encryption for stored files."""

    def __init__(self, enabled: bool, key: bytes | None) -> None:
        self.enabled = enabled
        self._key = key
        if enabled and (key is None or len(key) != 32):
            raise ValueError("AES-256-GCM requires a 32-byte encryption key")

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt plaintext and return nonce || ciphertext || tag."""
        if not self.enabled or self._key is None:
            raise AppError(
                "BAD_REQUEST",
                "Encryption is disabled on this server.",
                400,
            )
        try:
            nonce = get_random_bytes(NONCE_SIZE)
            cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce)
            ciphertext, tag = cipher.encrypt_and_digest(plaintext)
            return nonce + ciphertext + tag
        except AppError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Encryption failed")
            raise AppError(
                "INTERNAL_ERROR",
                "An unexpected error occurred while processing the request.",
                500,
                log_message="encryption failure",
            ) from exc

    def decrypt(self, payload: bytes) -> bytes:
        """Decrypt a payload produced by :meth:`encrypt`.

        Decryption is allowed whenever a key is configured, even if new
        encrypted uploads are disabled via ``ENCRYPTION_ENABLED=false``.
        """
        if self._key is None:
            raise AppError(
                "INTERNAL_ERROR",
                "An unexpected error occurred while processing the request.",
                500,
                log_message="decrypt called without encryption key",
            )
        if len(payload) < NONCE_SIZE + TAG_SIZE:
            raise AppError(
                "DECRYPTION_FAILED",
                "Unable to decrypt the requested file.",
                500,
            )
        nonce = payload[:NONCE_SIZE]
        tag = payload[-TAG_SIZE:]
        ciphertext = payload[NONCE_SIZE:-TAG_SIZE]
        try:
            cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce)
            return cipher.decrypt_and_verify(ciphertext, tag)
        except Exception as exc:
            logger.warning("Decryption failed: %s", type(exc).__name__)
            raise AppError(
                "DECRYPTION_FAILED",
                "Unable to decrypt the requested file.",
                500,
            ) from exc
