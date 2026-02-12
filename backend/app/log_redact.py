"""Secret redaction helpers for logging and URL safety."""

from __future__ import annotations

import logging
import re
import traceback
from urllib.parse import parse_qsl, quote_plus, urlsplit, urlunsplit

import httpx

SENSITIVE_QUERY_KEYS = frozenset(
    {
        "apikey",
        "api-key",
        "token",
        "access-token",
        "x-plex-token",
        "key",
        "secret",
        "password",
        "session",
        "auth",
    }
)
_SENSITIVE_KEY_PATTERN = r"(?:apikey|api_key|token|access_token|x-plex-token|key|secret|password|session|auth)"
_URL_PATTERN = re.compile(r"(?i)https?://[^\s\"'<>]+")
_JSON_SECRET_PATTERN = re.compile(
    rf"(?i)(\"{_SENSITIVE_KEY_PATTERN}\"[ \t]*:[ \t]*\")([^\"]*)(\")"
)
_KV_SECRET_PATTERN = re.compile(
    rf"(?i)(\b{_SENSITIVE_KEY_PATTERN}\b[ \t]*[=:][ \t]*)([^&\s,;\"'<>]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/]+=*")

_FILTER_LOGGERS = (
    "",
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "httpx",
    "httpcore",
    "marcle",
)
_HTTP_LOGGER = logging.getLogger("marcle.http")


def _normalize_query_key(key: str) -> str:
    return key.strip().lower().replace("_", "-")


def _is_sensitive_query_key(key: str) -> bool:
    normalized = _normalize_query_key(key)
    return normalized in SENSITIVE_QUERY_KEYS


def redact_url(url: str) -> str:
    """Redact sensitive query-param values in a URL and keep host/path visible."""
    if not url or "?" not in url:
        return url

    try:
        parsed = urlsplit(url)
    except ValueError:
        return url
    if not parsed.query:
        return url

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if not query_pairs:
        return url

    redacted_pairs: list[tuple[str, str]] = []
    changed = False
    for key, value in query_pairs:
        if _is_sensitive_query_key(key):
            redacted_pairs.append((key, "***"))
            changed = True
        else:
            redacted_pairs.append((key, value))
    if not changed:
        return url

    redacted_query = "&".join(
        f"{quote_plus(key)}={'***' if value == '***' else quote_plus(value)}"
        for key, value in redacted_pairs
    )
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            redacted_query,
            parsed.fragment,
        )
    )


def redact_text(value: str | None) -> str | None:
    """Redact common secret formats from arbitrary log text."""
    if value is None:
        return None
    text = str(value)

    text = _URL_PATTERN.sub(lambda match: redact_url(match.group(0)), text)
    text = _JSON_SECRET_PATTERN.sub(r"\1***\3", text)
    text = _KV_SECRET_PATTERN.sub(r"\1***", text)
    text = _BEARER_PATTERN.sub("Bearer ***", text)
    return text


class SecretRedactionFilter(logging.Filter):
    """Logging filter that redacts secrets before records are emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)

        record.msg = redact_text(message) or ""
        record.args = ()
        if record.exc_info:
            exc_text = "".join(traceback.format_exception(*record.exc_info))
            record.exc_text = redact_text(exc_text)
        return True


def _ensure_filter(logger: logging.Logger, redaction_filter: SecretRedactionFilter) -> None:
    if not any(isinstance(existing, SecretRedactionFilter) for existing in logger.filters):
        logger.addFilter(redaction_filter)
    for handler in logger.handlers:
        if not any(isinstance(existing, SecretRedactionFilter) for existing in handler.filters):
            handler.addFilter(redaction_filter)


def install_log_redaction() -> None:
    """Install process-wide log redaction and suppress raw httpx/httpcore INFO logs."""
    redaction_filter = SecretRedactionFilter()
    for logger_name in _FILTER_LOGGERS:
        _ensure_filter(logging.getLogger(logger_name), redaction_filter)

    # Disable default httpx/httpcore request-line logging to avoid raw URL leakage.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def _log_http_request(request: httpx.Request) -> None:
    _HTTP_LOGGER.debug("HTTP request method=%s url=%s", request.method, redact_url(str(request.url)))


async def _log_http_response(response: httpx.Response) -> None:
    request = response.request
    _HTTP_LOGGER.info(
        "HTTP response method=%s url=%s status=%d",
        request.method,
        redact_url(str(request.url)),
        response.status_code,
    )


def httpx_event_hooks() -> dict[str, list]:
    """Build event hooks for redacted request/response operational logging."""
    return {
        "request": [_log_http_request],
        "response": [_log_http_response],
    }
