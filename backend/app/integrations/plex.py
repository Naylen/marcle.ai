"""Plex integration helpers for identity and now-playing sessions."""

from __future__ import annotations

import logging
import os
import re
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
        sessions_http_status: int | None,
        sessions_parse_count: int,
        sessions_error_class: str | None,
        sessions_content_type: str | None = None,
        sessions_body_prefix: str | None = None,
        sessions_total_size: int | None = None,
        sessions_root_tag: str | None = None,
        sessions_child_tags_sample: list[str] | None = None,
    ) -> None:
        self.service_status = service_status
        self.now_playing = now_playing
        self.identity_ok = identity_ok
        self.sessions_ok = sessions_ok
        self.auth_ok = auth_ok
        self.sessions_http_status = sessions_http_status
        self.sessions_parse_count = sessions_parse_count
        self.sessions_error_class = sessions_error_class
        self.sessions_content_type = sessions_content_type
        self.sessions_body_prefix = sessions_body_prefix
        self.sessions_total_size = sessions_total_size
        self.sessions_root_tag = sessions_root_tag
        self.sessions_child_tags_sample = sessions_child_tags_sample or []


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
            "sessions_http_status": None,
            "sessions_parse_count": 0,
            "sessions_error_class": None,
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
            "sessions_http_status": None,
            "sessions_parse_count": 0,
            "sessions_error_class": "MissingCredentialError",
        }
        return base_status
    except InvalidCredentialFormatError:
        logger.warning("Invalid Plex credential format")
        base_status.extra = {
            "now_playing": [],
            "identity_ok": False,
            "sessions_ok": False,
            "auth_ok": True,
            "sessions_http_status": None,
            "sessions_parse_count": 0,
            "sessions_error_class": "InvalidCredentialFormatError",
        }
        return base_status

    result = await _probe_plex(service, auth_params)
    extra_payload = {
        "now_playing": result.now_playing,
        "identity_ok": result.identity_ok,
        "sessions_ok": result.sessions_ok,
        "auth_ok": result.auth_ok,
        "sessions_http_status": result.sessions_http_status,
        "sessions_parse_count": result.sessions_parse_count,
        "sessions_error_class": result.sessions_error_class,
    }
    if _debug_plex_sessions_enabled():
        extra_payload.update(
            {
                "sessions_content_type": result.sessions_content_type,
                "sessions_body_prefix": result.sessions_body_prefix,
                "sessions_total_size": result.sessions_total_size,
                "sessions_root_tag": result.sessions_root_tag,
                "sessions_child_tags_sample": result.sessions_child_tags_sample,
            }
        )
    result.service_status.extra = extra_payload
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
    sessions_http_status: int | None = None
    sessions_error_class: str | None = None
    sessions_content_type: str | None = None
    sessions_body_prefix: str | None = None
    sessions_total_size: int | None = None
    sessions_root_tag: str | None = None
    sessions_child_tags_sample: list[str] = []
    debug_enabled = _debug_plex_sessions_enabled()

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(verify=service.verify_ssl, timeout=timeout) as client:
            identity_response = await _get_plex_endpoint(client, service.url, "/identity", auth_params)
            identity_ok = 200 <= identity_response.status_code < 300
            if identity_response.status_code in {401, 403}:
                auth_ok = False

            sessions_response = await _get_plex_endpoint(client, service.url, "/status/sessions", auth_params)
            sessions_http_status = sessions_response.status_code
            sessions_ok = 200 <= sessions_response.status_code < 300
            sessions_content_type = sessions_response.headers.get("content-type")
            sessions_total_size = len(sessions_response.text or "")
            if debug_enabled:
                sessions_body_prefix = _redact_plex_token(sessions_response.text[:120])
            if sessions_response.status_code in {401, 403}:
                auth_ok = False

            if sessions_ok:
                now_playing, parse_error_class, sessions_root_tag, sessions_child_tags_sample = _parse_sessions_xml(
                    sessions_response.text
                )
                if parse_error_class:
                    sessions_error_class = parse_error_class
    except httpx.TimeoutException:
        logger.warning("Timeout probing Plex endpoints")
        sessions_error_class = "TimeoutException"
    except Exception as exc:
        logger.warning("Unexpected Plex probe error (%s)", exc.__class__.__name__)
        sessions_error_class = exc.__class__.__name__

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
        sessions_http_status=sessions_http_status,
        sessions_parse_count=len(now_playing),
        sessions_error_class=sessions_error_class,
        sessions_content_type=sessions_content_type,
        sessions_body_prefix=sessions_body_prefix,
        sessions_total_size=sessions_total_size,
        sessions_root_tag=sessions_root_tag,
        sessions_child_tags_sample=sessions_child_tags_sample,
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


def _parse_sessions_xml(payload: str) -> tuple[list[dict[str, Any]], str | None, str | None, list[str]]:
    if not payload or not payload.strip():
        return [], None, None, []

    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        logger.warning("Failed to parse Plex sessions XML")
        return [], "ParseError", None, []

    root_tag = _xml_local_name(root.tag)
    child_tags_sample = _sample_tags(root, max_items=10)

    sessions: list[dict[str, Any]] = []
    for item in _find_media_nodes(root):
        tag_name = _xml_local_name(item.tag)
        media_type = tag_name.lower()
        session = {
            "type": "video" if media_type == "video" else "track",
            "title": _attr_str(item, "title") or _attr_str(item, "grandparentTitle") or "Unknown",
            "grandparent": _attr_or_none(item, "grandparentTitle"),
            "parent": _attr_or_none(item, "parentTitle"),
            "user": _session_user(item) or _attr_or_none(item, "username"),
            "player": _session_player(item),
            "state": _session_state(item),
            "view_offset_ms": _attr_int(item, "viewOffset"),
            "duration_ms": _attr_int(item, "duration"),
        }
        sessions.append(session)

    return sessions, None, root_tag, child_tags_sample


def _session_user(item: ElementTree.Element) -> str | None:
    user = _find_first_child_by_local_name(item, "User")
    if user is not None:
        return _attr_or_none(user, "title") or _attr_or_none(user, "name")
    return None


def _session_player(item: ElementTree.Element) -> str | None:
    player = _find_first_child_by_local_name(item, "Player")
    if player is not None:
        return _attr_or_none(player, "title") or _attr_or_none(player, "product")
    return None


def _session_state(item: ElementTree.Element) -> str | None:
    player = _find_first_child_by_local_name(item, "Player")
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


def _find_media_nodes(root: ElementTree.Element) -> list[ElementTree.Element]:
    direct_matches = root.findall(".//Video") + root.findall(".//Track")
    if direct_matches:
        return direct_matches

    matches: list[ElementTree.Element] = []
    for node in root.iter():
        tag_name = _xml_local_name(node.tag)
        if tag_name in {"Video", "Track"}:
            matches.append(node)
    return matches


def _find_first_child_by_local_name(item: ElementTree.Element, local_name: str) -> ElementTree.Element | None:
    for child in item.iter():
        if child is item:
            continue
        if _xml_local_name(child.tag) == local_name:
            return child
    return None


def _sample_tags(root: ElementTree.Element, max_items: int) -> list[str]:
    tags: list[str] = []
    for node in root.iter():
        tag_name = _xml_local_name(node.tag)
        if not tag_name:
            continue
        tags.append(tag_name)
        if len(tags) >= max_items:
            break
    return tags


def _debug_plex_sessions_enabled() -> bool:
    return os.getenv("DEBUG_PLEX_SESSIONS", "").strip().lower() in {"1", "true", "yes", "on"}


def _redact_plex_token(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"(?i)X-Plex-Token=[^&\\s\"'<>]+", "X-Plex-Token=REDACTED", value)
