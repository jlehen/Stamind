"""The key, the names and the encryption, word for word as `miniapp/storage.js` does them
(DESIGN_miniapp_storage.md §5). A test holds one example both languages open.

`cryptography` is imported inside the functions that use it: it costs about 34 ms, and a
command pays it only when a bucket is configured (ARCHITECTURE.md §14, the startup path).
"""
import base64
import json
import os
import zlib
from typing import Any, Dict

# The label the page key is derived from the bot token with (§5).
PAGE_KEY_LABEL = b"stamind-miniapp-v1"

# The 12 bytes AES-GCM draws for each upload, written at the head of the file (§5).
NONCE_BYTES = 12


def _hkdf(secret: bytes, label: bytes, length: int) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=label).derive(secret)


def _aead(key: bytes):
    """AES-GCM under the key that encrypts, derived from the page key."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(_hkdf(key, b"file-key", 32))


def page_key(token: str) -> bytes:
    """The 32 bytes the button's address carries as `k=`, computed from the bot token."""
    return _hkdf(token.encode("utf-8"), PAGE_KEY_LABEL, 32)


def folder(token: str) -> str:
    """The bot's public number, the part of the token before the colon."""
    return token.split(":", 1)[0]


def file_name(key: bytes, label: str) -> str:
    """The name a file is stored under, such as September's for `calendar/2026-09`."""
    return _hkdf(key, b"name:" + label.encode("utf-8"), 16).hex()


def key_param(key: bytes) -> str:
    """The page key as the address writes it: base64url without padding."""
    return base64.urlsafe_b64encode(key).decode("ascii").rstrip("=")


def dumps(content: Dict[str, Any]) -> bytes:
    """A file's JSON, compact, as the button's data is written."""
    return json.dumps(content, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def seal(key: bytes, content: Dict[str, Any]) -> bytes:
    """The file's bytes: 12 fresh random bytes, then the JSON compressed and encrypted."""
    nonce = os.urandom(NONCE_BYTES)
    return nonce + _aead(key).encrypt(nonce, zlib.compress(dumps(content), 9), None)


def unseal(key: bytes, blob: bytes) -> Dict[str, Any]:
    """`seal`, undone."""
    plain = _aead(key).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], None)
    return json.loads(zlib.decompress(plain).decode("utf-8"))
