"""Authentication header construction for upstream checks."""

import base64
import os

from app.models import AuthRef


class MissingCredentialError(Exception):
    def __init__(self, env_name: str):
        super().__init__(f"Missing required credential env var: {env_name}")
        self.env_name = env_name


class InvalidCredentialFormatError(Exception):
    def __init__(self, env_name: str, scheme: str):
        super().__init__(f"Invalid credential format for scheme '{scheme}' in env var: {env_name}")
        self.env_name = env_name
        self.scheme = scheme


def build_auth_headers(auth_ref: AuthRef | None) -> dict[str, str]:
    if auth_ref is None or auth_ref.scheme == "none":
        return {}

    env_name = (auth_ref.env or "").strip()
    value = os.getenv(env_name)
    if not value:
        raise MissingCredentialError(env_name)

    if auth_ref.scheme == "bearer":
        return {"Authorization": f"Bearer {value}"}
    if auth_ref.scheme == "basic":
        if ":" not in value:
            raise InvalidCredentialFormatError(env_name, "basic")
        basic = base64.b64encode(value.encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {basic}"}
    if auth_ref.scheme == "header":
        return {auth_ref.header_name: value}  # validated in model
    return {}


def build_auth_params(auth_ref: AuthRef | None) -> dict[str, str]:
    """Returns query parameters derived from auth_ref."""
    if auth_ref is None or auth_ref.scheme == "none":
        return {}

    if auth_ref.scheme != "query_param":
        return {}

    env_name = (auth_ref.env or "").strip()
    if not env_name:
        raise MissingCredentialError("Missing auth env var name")

    value = os.getenv(env_name, "").strip()
    if not value:
        raise MissingCredentialError(env_name)

    return {auth_ref.param_name: value}  # validated in model
