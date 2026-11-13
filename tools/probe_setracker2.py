#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["cryptography>=42.0.0"]
# ///
"""Reproduce SeTracker2 crypto vectors and synthetic login probes.

This is a research tool, not a client profile. It never accepts real account
credentials or sends watch commands. Network access requires --live.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import ssl
import time
import urllib.request
from functools import reduce
from operator import xor
from pathlib import Path
from urllib.parse import quote

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

SIGN_KEY = "JKLDfjiow48fjklsSSDFASDFQPXJKLDKFJ34kfjsdoifjw"
HMAC_SIGN_FLAG = "aKsdj93kf93jfcdkjaoskjfLAKlWKEJF92lsdLFKkfjsdlfkj"
ENVELOPE_KEY = bytes.fromhex("d95337bb49ea14f4d47bcd36f777c07e")
ENVELOPE_IV = bytes.fromhex("0dd9444f8132b092373afd8c74629fed")
CREDENTIAL_KEY = bytes.fromhex("87fe6ba20a09adc5ef5183ac26cf509b")
CREDENTIAL_IV = bytes.fromhex("125648f3f4f79c928d6fd7145ca6100a")
ACCOUNT = "codex-protocol-probe@example.invalid"
PASSWORD = "SyntheticProtocolProbe-2026"


def aes_encrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    padder = PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def decrypt_envelope(payload: dict[str, object]) -> dict[str, object]:
    if payload.get("encryptIndex") != 22:
        raise ValueError(f"Unexpected response encryption index: {payload.get('encryptIndex')!r}")
    decryptor = Cipher(algorithms.AES(ENVELOPE_KEY), modes.CBC(ENVELOPE_IV)).decryptor()
    padded = decryptor.update(bytes.fromhex(str(payload["encryptData"]))) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    result = json.loads(unpadder.update(padded) + unpadder.finalize())
    if not isinstance(result, dict):
        raise ValueError("Unexpected non-object decrypted response")
    return result


def new_password(login: str, password: str) -> str:
    # ASCII research inputs only; this does not implement JNI Modified UTF-8.
    combined = aes_encrypt(login.encode("ascii"), CREDENTIAL_KEY, CREDENTIAL_IV)
    combined += hashlib.md5(password.encode("ascii")).digest()
    return hashlib.sha256(combined).hexdigest().upper() + f"{reduce(xor, combined):02X}"


def hmac_sign(params: dict[str, str], *, include_sign_flag: bool = False) -> str:
    # include_sign_flag is used only by the invalid-signature control.
    excluded = {"sign", "encrypted_aes_key", "encrypted_aes_iv"}
    if not include_sign_flag:
        excluded.add("sign_flag")
    canonical = "&".join(
        key + "=" + quote(value, safe="-_.!~*'()")
        for key, value in sorted(params.items())
        if key not in excluded
    )
    return hmac.new(
        SIGN_KEY.encode(), (canonical + "&key=" + SIGN_KEY).encode(), hashlib.sha256
    ).hexdigest().upper()


def legacy_sign(params: dict[str, str]) -> str:
    value = "SECRPRO" + "".join(key + val for key, val in sorted(params.items())) + "SECRPRO"
    for _ in range(3):
        value = hashlib.md5(value.encode()).hexdigest()
    return hashlib.sha256(value.encode()).hexdigest()


def verify_vectors() -> None:
    """Check signature, credential, and native AES reference vectors."""
    params = {
        "app_flag": "70", "count": "300", "createtime": "2026-11-11 13:38:50",
        "did": "3707897174", "did_id": "157868774", "flag": "3",
        "language": "enUS", "timestamppp": "1794500680652",
    }
    signature = hmac_sign(params)
    with_metadata = params | {
        "sign_flag": HMAC_SIGN_FLAG, "sign": "ignored",
        "encrypted_aes_key": "ignored", "encrypted_aes_iv": "ignored",
    }
    checks = {
        "HMAC": signature == "251998574CF6CB744466F48AE6A0A3119C1E92B031FD9D4072C3CCB32154E0CA",
        "excluded signing metadata": hmac_sign(with_metadata) == signature,
        "signed flag changes signature": hmac_sign(with_metadata, include_sign_flag=True) != signature,
        "app_flag remains signed": hmac_sign(params | {"app_flag": "394"}) != signature,
        "credential": new_password("alice@example.test", "ExamplePassword!")
        == "FC3D66F7764F1A9C435F8374D99D32AF27F63AF525F1300A33B29E6D51776EA860",
        "native AES": aes_encrypt(
            b'{"synthetic":"alice@example.test","app_flag":"70"}', ENVELOPE_KEY, ENVELOPE_IV
        ).hex() == (
            "25c7de4cd8e956051147ad52305880f65258b7e7f6af666add22749f0b80cd5a5"
            "2c7aefc0ef507244980c3fa08b971e2ef13778ff223b9e1fddc70867809b0aa"
        ),
    }
    if not all(checks.values()):
        raise RuntimeError(f"Reference vector mismatch: {checks}")
    print(json.dumps({"offline_vectors": checks}))


def probe(case: str, context: ssl.SSLContext) -> dict[str, object]:
    params = {
        "app_flag": "70", "appid": "aaagg10006", "flag": "70", "isIPHONE": "1",
        "language": "enUS", "loginname": ACCOUNT, "newpassword": new_password(ACCOUNT, PASSWORD),
        "password": hashlib.sha256(hashlib.md5(PASSWORD.encode()).hexdigest().encode()).hexdigest(),
        "timestamppp": str(int(time.time() * 1000)), "version": "3.3.5",
    }
    if case in {"legacy_with_flag", "invalid_legacy_signature"}:
        params["sign_flag"] = "KHDIW"
    elif case not in {"hmac_without_flag", "legacy_without_flag"}:
        params["sign_flag"] = HMAC_SIGN_FLAG
    params["sign"] = (
        legacy_sign(params) if "legacy" in case
        else hmac_sign(params, include_sign_flag=case == "hmac_flag_included_in_signature")
    )
    if case in {"invalid_legacy_signature", "invalid_hmac_signature"}:
        params["sign"] = "0" * 64
    ciphertext = aes_encrypt(
        json.dumps(params, separators=(",", ":")).encode(), ENVELOPE_KEY, ENVELOPE_IV
    )
    if case == "invalid_ciphertext":
        ciphertext = bytes(16)
    envelope = {"encryptIndex": 22, "encryptData": ciphertext.hex().upper()}
    request = urllib.request.Request(
        "https://europe.myaqsh.com:9401/app/public/S10APP/v2_new_userLogin2",
        data=json.dumps(envelope).encode(),
        headers={"Content-Type": "application/json; charset=utf-8", "X-Encrypt-Index": "22"},
        method="POST",
    )
    with urllib.request.urlopen(request, context=context, timeout=20) as response:
        payload = json.load(response)
        http_status = response.status
    if not isinstance(payload, dict):
        raise ValueError("Unexpected non-object response")
    encrypted = "encryptData" in payload
    if encrypted:
        payload = decrypt_envelope(payload)
    return {"case": case, "http_status": http_status, "encrypted_response": encrypted,
            "status": payload.get("status"),
            "message": payload.get("message")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Send eight synthetic login probes to Europe :9401")
    args = parser.parse_args()
    verify_vectors()
    if not args.live:
        return
    context = ssl.create_default_context()
    certificate = Path(__file__).resolve().parents[1] / "custom_components/yqt/core/client.pem"
    context.load_cert_chain(certificate, password="yqt-smart-api")
    for case in ("hmac_without_flag", "hmac_with_flag",
                 "hmac_flag_included_in_signature", "invalid_hmac_signature",
                 "legacy_without_flag", "legacy_with_flag",
                 "invalid_legacy_signature", "invalid_ciphertext"):
        print(json.dumps(probe(case, context)))


if __name__ == "__main__":
    main()
