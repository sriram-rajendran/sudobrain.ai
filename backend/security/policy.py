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


DEFAULT_QUOTAS = [
    Quota("api_requests", int(os.getenv("SUDOBRAIN_QUOTA_API_REQUESTS", "600")), 60),
    Quota("provider_tests", int(os.getenv("SUDOBRAIN_QUOTA_PROVIDER_TESTS", "30")), 3600),
    Quota("sync_runs", int(os.getenv("SUDOBRAIN_QUOTA_SYNC_RUNS", "12")), 3600),
]


def security_policy() -> dict:
    mode = os.getenv("SUDOBRAIN_AUTH_MODE", "local_single_user")
    active_role = os.getenv("SUDOBRAIN_LOCAL_ROLE", "owner")
    return {
        "mode": mode,
        "local_role": active_role,
        "roles": ROLES,
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
        },
    }
