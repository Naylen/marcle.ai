"""Plex integration helpers for identity and now-playing sessions."""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx

from app import config
from app.auth import InvalidCredentialFormatError, MissingCredentialError, build_auth_params
from app.models import AuthRef, ServiceConfig, ServiceStatus, Status

logger = logging.getLogger("marcle.integrations.plex")


class PlexProbeResult:
    def __init__(
        self,
        *,
        service_status: ServiceStatus,
        now_playing: list[dict[str, Any]],
        identity_ok: bool,
        sessions_ok: bool,
        auth_ok: bool,
    ) -> None:
        self.service_status = service_status
        self.now_playing = now_playing
        self.identity_ok = identity_ok
        self.sessions_ok = sessions_ok
        self.auth_ok = auth_ok


async def check_plex_service(service: ServiceConfig) -> ServiceStatus:
    """Check Plex identity + sessions and attach normalized now_playing payload."""
    base_status = ServiceStatus(
        id=service.id,
        name=service.name,
        group=service.group,
        status=Status.UNKNOWN,
        latency_ms=None,
        url=service.url,
        description=service.description,
        icon=service.icon,
    )

    if not service.url:
        base_status.extra = {
            "now_playing": [],
            "identity_ok": False,
            "sessions_ok": False,
            "auth_ok": True,
        }
        return base_status

    auth_ref = _plex_query_param_auth_ref(service)
    try:
        auth_params = build_auth_params(auth_ref)
    except MissingCredentialError:
        logger.warning("Missing Plex credential env var")
        base_status.extra = {
            "now_playing": [],
            "identity_ok": False,
            "sessions_ok": False,
            "auth_ok": True,
        }
        return base_status
    except InvalidCredentialFormatError:
        logger.warning("Invalid Plex credential format")
        base_status.extra = {
            "now_playing": [],
            "identity_ok": False,
            "sessions_ok": False,
            "auth_ok": True,
        }
        return base_status

    result = await _probe_plex(service, auth_params)
    result.service_status.extra = {
        "now_playing": result.now_playing,
        "identity_ok": result.identity_ok,
        "sessions_ok": result.sessions_ok,
        "auth_ok": result.auth_ok,
    }
    return result.service_status


def _plex_query_param_auth_ref(service: ServiceConfig) -> AuthRef:
    if service.auth_ref and service.auth_ref.scheme == "query_param":
        param_name = service.auth_ref.param_name or "X-Plex-Token"
        return AuthRef(scheme="query_param", env=service.auth_ref.env, param_name=param_name)

    env_name = "PLEX_TOKEN"
    if service.auth_ref and service.auth_ref.env:
        env_name = service.auth_ref.env
    return AuthRef(scheme="query_param", env=env_name, param_name="X-Plex-Token")


async def _probe_plex(service: ServiceConfig, auth_params: dict[str, str]) -> PlexProbeResult:
    timeout = httpx.Timeout(timeout=config.REQUEST_TIMEOUT_SECONDS)
    identity_ok = False
    sessions_ok = False
    auth_ok = True
    now_playing: list[dict[str, Any]] = []

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(verify=service.verify_ssl, timeout=timeout) as client:
            identity_response = await _get_plex_endpoint(client, service.url, "/identity", auth_params)
            identity_ok = 200 <= identity_response.status_code < 300
            if identity_response.status_code in {401, 403}:
                auth_ok = False

            sessions_response = await _get_plex_endpoint(client, service.url, "/status/sessions", auth_params)
            sessions_ok = 200 <= sessions_response.status_code < 300
            if sessions_response.status_code in {401, 403}:
                auth_ok = False

            if sessions_ok:
                now_playing = _parse_sessions_xml(sessions_response.text)
    except httpx.TimeoutException:
        logger.warning("Timeout probing Plex endpoints")
    except Exception as exc:
        logger.warning("Unexpected Plex probe error (%s)", exc.__class__.__name__)

    latency = int((time.monotonic() - start) * 1000)

    status_value = Status.HEALTHY if identity_ok else Status.UNKNOWN
    service_status = ServiceStatus(
        id=service.id,
        name=service.name,
        group=service.group,
        status=status_value,
        latency_ms=latency,
        url=service.url,
        description=service.description,
        icon=service.icon,
    )

    return PlexProbeResult(
        service_status=service_status,
        now_playing=now_playing,
        identity_ok=identity_ok,
        sessions_ok=sessions_ok,
        auth_ok=auth_ok,
    )


async def _get_plex_endpoint(
    client: httpx.AsyncClient,
    base_url: str,
    path: str,
    auth_params: dict[str, str],
) -> httpx.Response:
    full_url = base_url.rstrip("/") + path
    parsed_url = urlsplit(full_url)
    base_query = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
    clean_url = urlunsplit((parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", parsed_url.fragment))

    request_params = dict(base_query)
    request_params.update(auth_params)
    return await client.get(clean_url, params=request_params)


def _parse_sessions_xml(payload: str) -> list[dict[str, Any]]:
    if not payload or not payload.strip():
        return []

    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        logger.warning("Failed to parse Plex sessions XML")
        return []

    sessions: list[dict[str, Any]] = []
    for item in root.iter():
        tag_name = _xml_local_name(item.tag)
        if tag_name not in {"Video", "Track"}:
            continue
        media_type = tag_name.lower()
        session = {
            "type": "video" if media_type == "video" else "track",
            "title": _attr_str(item, "title") or "Unknown",
            "grandparent": _attr_or_none(item, "grandparentTitle"),
            "parent": _attr_or_none(item, "parentTitle"),
            "user": _session_user(item),
            "player": _session_player(item),
            "state": _session_state(item),
            "view_offset_ms": _attr_int(item, "viewOffset"),
            "duration_ms": _attr_int(item, "duration"),
        }
        sessions.append(session)

    return sessions


def _session_user(item: ElementTree.Element) -> str | None:
    user = item.find("./User") or item.find(".//User")
    if user is not None:
        return _attr_or_none(user, "title") or _attr_or_none(user, "name")
    return None


def _session_player(item: ElementTree.Element) -> str | None:
    player = item.find("./Player") or item.find(".//Player")
    if player is not None:
        return _attr_or_none(player, "title") or _attr_or_none(player, "product")
    return None


def _session_state(item: ElementTree.Element) -> str | None:
    player = item.find("./Player") or item.find(".//Player")
    if player is not None:
        return _attr_or_none(player, "state")
    return None


def _attr_str(item: ElementTree.Element, key: str) -> str | None:
    value = item.get(key)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _attr_or_none(item: ElementTree.Element, key: str) -> str | None:
    return _attr_str(item, key)


def _attr_int(item: ElementTree.Element, key: str) -> int | None:
    value = _attr_str(item, key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _xml_local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag
