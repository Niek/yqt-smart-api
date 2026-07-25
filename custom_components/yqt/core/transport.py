from __future__ import annotations

import json
import secrets
import ssl
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from .protocol import DEFAULT_CLIENT_FLAG, YQTError, compute_sign


CLIENT_CERTIFICATE = Path(__file__).with_name("client.pem")
CLIENT_CERTIFICATE_PASSWORD = "yqt-smart-api"
ENCRYPT_INDEX_HEADER = "X-Encrypt-Index"

_CIPHERS = {
    1: (b"c04680dcfacba69d", b"c6e134f528459fe0"),
    2: (b"029fd8027e50b5f7", b"d69026a0c6550792"),
    3: (b"bdc637d99503579d", b"562d9ee5da4daa34"),
    4: (b"ee3fa426e9acc406", b"6ee2d4bec18f67e3"),
    5: (b"e439c3a631357fe3", b"e4f8b2aa45f3e159"),
}


def create_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.load_cert_chain(
        CLIENT_CERTIFICATE,
        password=CLIENT_CERTIFICATE_PASSWORD,
    )
    return context


def encrypt_request(
    params: dict[str, Any],
    *,
    form_encoded: bool,
    index: int | None = None,
) -> tuple[dict[str, int | str], int]:
    unsigned = {
        key: str(value)
        for key, value in params.items()
        if value is not None and key != "sign"
    }
    unsigned.setdefault("app_flag", str(DEFAULT_CLIENT_FLAG))

    signed = dict(unsigned)
    signed["sign"] = compute_sign(unsigned)
    if form_encoded:
        signed = {
            quote_plus(key, safe=""): quote_plus(value, safe="")
            for key, value in signed.items()
        }

    selected_index = index if index is not None else secrets.randbelow(len(_CIPHERS)) + 1
    encrypted = _encrypt(
        json.dumps(signed, ensure_ascii=False, separators=(",", ":")).encode(),
        selected_index,
    )
    return {
        "encryptIndex": selected_index,
        "encryptData": encrypted.hex(),
    }, selected_index


def decrypt_response(payload: dict[str, Any]) -> dict[str, Any]:
    encrypted = payload.get("encryptData")
    index = payload.get("encryptIndex")
    if not isinstance(encrypted, str) or not encrypted:
        return payload

    try:
        selected_index = int(index)
        decrypted = _decrypt(bytes.fromhex(encrypted), selected_index)
        result = json.loads(decrypted)
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise YQTError("server returned an invalid encrypted response") from exc

    if not isinstance(result, dict):
        raise YQTError("server returned a non-object encrypted response")
    return result


def _encrypt(data: bytes, index: int) -> bytes:
    key, iv = _cipher(index)
    padder = PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(data) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _decrypt(data: bytes, index: int) -> bytes:
    key, iv = _cipher(index)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(data) + decryptor.finalize()
    unpadder = PKCS7(algorithms.AES.block_size).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def _cipher(index: int) -> tuple[bytes, bytes]:
    try:
        return _CIPHERS[index]
    except KeyError as exc:
        raise YQTError(f"unsupported encryption index {index}") from exc
