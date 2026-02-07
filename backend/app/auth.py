"""Environment-backed credential resolution for service health checks.

This module reads secret values from environment variables at runtime.
Secret values are **never** persisted, logged, or returned via any API.
"""

import base64
import logging
import os
from typing import Optional

from app.models import AuthRef

logger = logging.getLogger("marcle.auth")


class MissingCredentialError(Exception):
    """Raised when a required env var is not set."""

    def __init__(self, env_name: str) -> None:
        self.env_name = env_name
        super().__init__(f"Environment variable {env_name!r} is not set")


def build_auth_headers(auth_ref: Optional[AuthRef]) -> dict[str, str]:
    """Resolve an AuthRef into HTTP headers using environment variables.

    Returns an empty dict for scheme ``"none"`` or when *auth_ref* is None.

    Raises :class:`MissingCredentialError` if the referenced env var is
    unset or empty — callers should catch this and degrade gracefully.
    """
    if auth_ref is None or auth_ref.scheme == "none":
        return {}

    value = os.environ.get(auth_ref.env, "").strip()
    if not value:
        # Log the env var *name* (safe) — never the value.
        logger.warning(
            "Credential env var %r (scheme=%s) is not set",
            auth_ref.env,
            auth_ref.scheme,
        )
        raise MissingCredentialError(auth_ref.env)

    if auth_ref.scheme == "bearer":
        return {"Authorization": f"Bearer {value}"}

    if auth_ref.scheme == "basic":
        # Expect value in "user:pass" format.
        encoded = base64.b64encode(value.encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

    if auth_ref.scheme == "header":
        # header_name is validated non-empty by the model when scheme="header".
        return {auth_ref.header_name: value}  # type: ignore[dict-item]

    return {}
