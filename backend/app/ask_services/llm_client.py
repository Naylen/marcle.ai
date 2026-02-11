"""Shared OpenAI-compatible chat completion client."""

from __future__ import annotations

import logging
from urllib.parse import urlparse, urlunparse

import httpx

logger = logging.getLogger("marcle.ask.llm.client")


class LLMClientError(RuntimeError):
    """Raised when an OpenAI-compatible request fails or has no usable output."""


def _with_path(parsed, path: str) -> str:
    clean_path = f"/{path.lstrip('/')}"
    return urlunparse((parsed.scheme, parsed.netloc, clean_path, "", "", ""))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def build_chat_completion_urls(base_url: str) -> list[str]:
    """Build one or more candidate chat-completion URLs from a base URL."""
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        raise LLMClientError("LLM base URL is not configured")

    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        raise LLMClientError(f"Invalid LLM base URL: {base_url!r}")

    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        return [normalized]

    candidates: list[str] = []
    if path in {"", "/"}:
        candidates.append(_with_path(parsed, "/v1/chat/completions"))
        candidates.append(_with_path(parsed, "/engines/v1/chat/completions"))
        return _dedupe(candidates)

    if path.endswith("/engines/v1"):
        prefix = path.removesuffix("/engines/v1")
        candidates.append(_with_path(parsed, f"{path}/chat/completions"))
        candidates.append(_with_path(parsed, f"{prefix}/v1/chat/completions"))
        return _dedupe(candidates)

    if path.endswith("/v1"):
        prefix = path.removesuffix("/v1")
        candidates.append(_with_path(parsed, f"{path}/chat/completions"))
        candidates.append(_with_path(parsed, f"{prefix}/engines/v1/chat/completions"))
        return _dedupe(candidates)

    candidates.append(_with_path(parsed, f"{path}/chat/completions"))
    return _dedupe(candidates)


def _extract_text_content(data: dict) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""
    message = first_choice.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n".join(parts).strip()
    return ""


def _normalize_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    if not messages:
        raise LLMClientError("At least one message is required")

    normalized: list[dict[str, str]] = []
    for item in messages:
        role = str(item.get("role", "")).strip()
        content = str(item.get("content", "")).strip()
        if not role or not content:
            continue
        normalized.append({"role": role, "content": content})

    if not normalized:
        raise LLMClientError("No valid messages provided")

    system_indexes = [index for index, item in enumerate(normalized) if item.get("role") == "system"]
    if not system_indexes:
        raise LLMClientError("System message is required and must be first in payload")

    first_system_index = system_indexes[0]
    if first_system_index != 0:
        system_message = normalized.pop(first_system_index)
        normalized.insert(0, system_message)
    return normalized


async def call_openai_compatible(
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    messages: list[dict[str, str]],
    timeout_seconds: float,
    temperature: float = 0.3,
    max_tokens: int = 600,
) -> str:
    """Call an OpenAI-compatible chat-completions endpoint and return output text."""
    if not model.strip():
        raise LLMClientError("LLM model is not configured")

    urls = build_chat_completion_urls(base_url)
    headers = {"Content-Type": "application/json"}
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    normalized_messages = _normalize_messages(messages)
    safe_temperature = max(0.0, min(float(temperature), 2.0))
    safe_max_tokens = max(1, min(int(max_tokens), 4000))
    payload = {
        "model": model.strip(),
        "messages": normalized_messages,
        "temperature": safe_temperature,
        "max_tokens": safe_max_tokens,
    }

    timeout = httpx.Timeout(max(float(timeout_seconds), 1.0))
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout) as client:
        for index, url in enumerate(urls):
            try:
                response = await client.post(url, json=payload, headers=headers)
            except Exception as exc:
                last_error = exc
                if index < len(urls) - 1:
                    logger.warning("LLM request transport error on %s, trying next candidate URL", url)
                    continue
                raise LLMClientError(f"LLM request failed: {exc.__class__.__name__}") from exc

            if response.status_code >= 400:
                body_preview = response.text[:300]
                if response.status_code in {404, 405} and index < len(urls) - 1:
                    logger.warning(
                        "LLM endpoint candidate rejected status=%d url=%s body=%s; trying fallback URL",
                        response.status_code,
                        url,
                        body_preview,
                    )
                    continue
                raise LLMClientError(
                    f"LLM request failed status={response.status_code} url={url} body={body_preview}"
                )

            try:
                data = response.json()
            except ValueError as exc:
                raise LLMClientError("LLM response is not valid JSON") from exc

            content = _extract_text_content(data if isinstance(data, dict) else {})
            if not content:
                raise LLMClientError("LLM response did not include content")
            return content

    if last_error is not None:
        raise LLMClientError(f"LLM request failed: {last_error.__class__.__name__}") from last_error
    raise LLMClientError("No valid LLM endpoint URL candidates")
