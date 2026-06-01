"""Local security policy scaffolding for single-user and future team modes."""

from __future__ import annotations

import os
from dataclasses import dataclass


ROLES = {
    "owner": ["read", "write", "admin", "approve"],
    "editor": ["read", "write"],
    "viewer": ["read"],
}


@dataclass(frozen=True)
class Quota:
    name: str
    limit: int
    window_seconds: int


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or str(default))
    except ValueError:
        return default


DEFAULT_QUOTAS = [
    Quota("api_requests", _int_env("SUDOBRAIN_QUOTA_API_REQUESTS", 600), 60),
    Quota("provider_tests", _int_env("SUDOBRAIN_QUOTA_PROVIDER_TESTS", 30), 3600),
    Quota("sync_runs", _int_env("SUDOBRAIN_QUOTA_SYNC_RUNS", 12), 3600),
]


def security_policy() -> dict:
    mode = os.getenv("SUDOBRAIN_AUTH_MODE", "local_single_user")
    active_role = os.getenv("SUDOBRAIN_LOCAL_ROLE", "owner")
    return {
        "mode": mode,
        "local_role": active_role,
        "roles": ROLES,
        "rbac_enforced": True,
        "multi_user_ready": mode != "local_single_user",
        "sso": {
            "enabled": bool(os.getenv("SUDOBRAIN_SSO_ISSUER")),
            "issuer_configured": bool(os.getenv("SUDOBRAIN_SSO_ISSUER")),
            "client_id_configured": bool(os.getenv("SUDOBRAIN_SSO_CLIENT_ID")),
        },
        "quotas": [quota.__dict__ for quota in DEFAULT_QUOTAS],
        "secrets": {
            "backend": os.getenv("SUDOBRAIN_SECRET_BACKEND", "environment"),
            "encrypted_local_store": bool(os.getenv("SUDOBRAIN_SECRETS_KEY")),
            "status_endpoint": "/security/secrets/status",
        },
    }
