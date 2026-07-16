"""Encryption and opaque action-context helpers for Lark."""

import base64
import hashlib
import json
from collections.abc import Mapping

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from recipe_agent.domain.common.types import JsonValue


class LarkDecryptionError(ValueError):
    """An encrypted callback could not be authenticated or decoded."""


class LarkCipher:
    """Decrypt Lark AES-256-CBC callback envelopes."""

    def __init__(self, encrypt_key: str) -> None:
        self._key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()

    def decrypt(self, encrypted: str) -> dict[str, JsonValue]:
        try:
            ciphertext = base64.b64decode(encrypted, validate=True)
            decryptor = Cipher(algorithms.AES(self._key), modes.CBC(self._key[:16])).decryptor()
            padded = decryptor.update(ciphertext) + decryptor.finalize()
            unpadder = PKCS7(algorithms.AES.block_size).unpadder()
            plaintext = unpadder.update(padded) + unpadder.finalize()
            payload = json.loads(plaintext)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise LarkDecryptionError("Invalid encrypted Lark payload") from error
        if not isinstance(payload, dict):
            raise LarkDecryptionError("Lark payload must be an object")
        return payload


class ActionContextSigner:
    """Encrypt and authenticate card action context."""

    def __init__(self, signing_key: str) -> None:
        key = base64.urlsafe_b64encode(hashlib.sha256(signing_key.encode("utf-8")).digest())
        self._fernet = Fernet(key)

    def dumps(self, values: Mapping[str, JsonValue]) -> str:
        serialized = json.dumps(values, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return self._fernet.encrypt(serialized).decode("ascii")

    def loads(self, token: str) -> dict[str, JsonValue]:
        try:
            payload = json.loads(self._fernet.decrypt(token.encode("ascii")))
        except (InvalidToken, UnicodeError, json.JSONDecodeError) as error:
            raise LarkDecryptionError("Invalid action context") from error
        if not isinstance(payload, dict):
            raise LarkDecryptionError("Action context must be an object")
        return payload
