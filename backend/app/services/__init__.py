"""Shared utilities for service health checks."""

import time
import logging
from typing import Optional, Iterable
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import httpx

from app import config
from app.auth import InvalidCredentialFormatError, MissingCredentialError, build_auth_headers, build_auth_params
from app.models import AuthRef, ServiceStatus, Status, ServiceGroup

logger = logging.getLogger("marcle.services")

TIMEOUT = httpx.Timeout(timeout=config.REQUEST_TIMEOUT_SECONDS)


async def http_check(
    *,
    id: str,
    name: str,
    group: ServiceGroup,
    url: str,
    path: str = "/",
    params: Optional[dict[str, str]] = None,
    headers: Optional[dict] = None,
    auth_ref: Optional[AuthRef] = None,
    verify_ssl: bool = False,
    description: Optional[str] = None,
    icon: Optional[str] = None,
    healthy_status_codes: Optional[Iterable[int]] = None,
) -> ServiceStatus:
    """Generic HTTP health check. Returns ServiceStatus, never raises."""
    if not url:
        return ServiceStatus(
            id=id, name=name, group=group, status=Status.UNKNOWN,
            description=description, icon=icon,
        )

    full_url = url.rstrip("/") + path
    parsed_url = urlsplit(full_url)
    base_query_params = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
    full_url = urlunsplit((parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", parsed_url.fragment))
    expected_codes = set(healthy_status_codes or {200})

    request_headers = dict(headers or {})
    try:
        request_headers.update(build_auth_headers(auth_ref))
        auth_params = build_auth_params(auth_ref)
        request_params = dict(base_query_params)
        request_params.update(params or {})
        request_params.update(auth_params)
    except MissingCredentialError as exc:
        logger.warning("Missing credential env var for %s: %s", id, exc.env_name)
        return ServiceStatus(
            id=id,
            name=name,
            group=group,
            status=Status.UNKNOWN,
            url=url,
            description=description,
            icon=icon,
        )
    except InvalidCredentialFormatError as exc:
        logger.warning("Invalid %s credential format for %s in %s", exc.scheme, id, exc.env_name)
        return ServiceStatus(
            id=id,
            name=name,
            group=group,
            status=Status.UNKNOWN,
            url=url,
            description=description,
            icon=icon,
        )

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(verify=verify_ssl, timeout=TIMEOUT) as client:
            resp = await client.get(full_url, headers=request_headers, params=request_params)
        latency = int((time.monotonic() - start) * 1000)

        status = Status.HEALTHY if resp.status_code in expected_codes else Status.DEGRADED

        return ServiceStatus(
            id=id, name=name, group=group, status=status,
            latency_ms=latency, url=url, description=description, icon=icon,
        )
    except httpx.TimeoutException:
        logger.warning("Timeout checking %s", id)
        return ServiceStatus(
            id=id, name=name, group=group, status=Status.UNKNOWN,
            url=url, description=description, icon=icon,
        )
    except Exception as exc:
        logger.warning("Error checking %s (%s)", id, exc.__class__.__name__)
        return ServiceStatus(
            id=id, name=name, group=group, status=Status.UNKNOWN,
            url=url, description=description, icon=icon,
        )
