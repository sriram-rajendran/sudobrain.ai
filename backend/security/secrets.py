"""Encrypted local secret storage for opt-in provider and integration keys."""

from __future__ import annotations

import json
import os
from pathlib import Path


SECRET_STORE_PATH = Path(os.getenv("SUDOBRAIN_SECRET_STORE_PATH", os.path.expanduser("~/.sudobrain/secrets.enc")))


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except Exception as exc:
        raise RuntimeError("cryptography is required for encrypted local secrets") from exc
    key = os.getenv("SUDOBRAIN_SECRETS_KEY", "")
    if not key:
        raise RuntimeError("SUDOBRAIN_SECRETS_KEY is required for encrypted local secrets")
    return Fernet(key.encode("utf-8"))


def generate_key() -> str:
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode("utf-8")


def status() -> dict:
    return {
        "backend": "encrypted_file",
        "configured": bool(os.getenv("SUDOBRAIN_SECRETS_KEY")),
        "path": str(SECRET_STORE_PATH),
        "exists": SECRET_STORE_PATH.exists(),
    }


def _read_store() -> dict[str, str]:
    if not SECRET_STORE_PATH.exists():
        return {}
    decrypted = _fernet().decrypt(SECRET_STORE_PATH.read_bytes())
    payload = json.loads(decrypted.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_store(payload: dict[str, str]) -> None:
    SECRET_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SECRET_STORE_PATH.write_bytes(_fernet().encrypt(json.dumps(payload, sort_keys=True).encode("utf-8")))
    SECRET_STORE_PATH.chmod(0o600)


def list_secret_names() -> list[str]:
    return sorted(_read_store().keys())


def put_secret(name: str, value: str) -> dict:
    if not name or len(name) > 120:
        raise ValueError("Secret name must be 1-120 characters")
    payload = _read_store()
    payload[name] = value
    _write_store(payload)
    return {"status": "stored", "name": name}


def delete_secret(name: str) -> dict:
    payload = _read_store()
    existed = name in payload
    payload.pop(name, None)
    _write_store(payload)
    return {"status": "deleted" if existed else "missing", "name": name}
