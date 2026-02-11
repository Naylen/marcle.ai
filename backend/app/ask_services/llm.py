"""Ask fallback LLM providers (local first, OpenAI second)."""

from __future__ import annotations

import os

from app.ask_services.llm_client import call_openai_compatible

LOCAL_LLM_BASE_URL: str = os.getenv("LOCAL_LLM_BASE_URL", "http://172.16.2.220:12434/engines/v1")
LOCAL_LLM_API_KEY: str = os.getenv("LOCAL_LLM_API_KEY", "not-needed")
LOCAL_LLM_MODEL: str = os.getenv("LOCAL_LLM_MODEL", "ai/llama3.2:latest")
LOCAL_LLM_TIMEOUT_SECONDS: float = float(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "90"))

# Existing LLM_* vars remain the OpenAI fallback configuration for compatibility.
OPENAI_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
OPENAI_API_KEY: str = os.getenv("LLM_API_KEY", "")
OPENAI_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
OPENAI_TIMEOUT_SECONDS: float = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "600"))

_SYSTEM_PROMPT = (
    "You are a backend support assistant for marcle.ai. "
    "Provide concise, practical answers in plain text. "
    "If key details are missing, state your assumptions and ask 1-2 targeted clarifying questions. "
    "Do not reveal secrets, tokens, private keys, passwords, or internal credentials. "
    "If asked for sensitive data, refuse and suggest a safe alternative."
)


def _build_messages(question_text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": question_text},
    ]


async def generate_local_answer_text(question_text: str) -> str:
    """Generate answer text from the local Docker Model Runner endpoint."""
    return await call_openai_compatible(
        base_url=LOCAL_LLM_BASE_URL,
        api_key=LOCAL_LLM_API_KEY,
        model=LOCAL_LLM_MODEL,
        messages=_build_messages(question_text),
        timeout_seconds=LOCAL_LLM_TIMEOUT_SECONDS,
    )


async def generate_openai_answer_text(question_text: str) -> str:
    """Generate answer text from OpenAI as stage-3 fallback."""
    if not OPENAI_API_KEY.strip():
        raise RuntimeError("LLM_API_KEY is required for OpenAI fallback")
    return await call_openai_compatible(
        base_url=OPENAI_BASE_URL,
        api_key=OPENAI_API_KEY,
        model=OPENAI_MODEL,
        messages=_build_messages(question_text),
        timeout_seconds=OPENAI_TIMEOUT_SECONDS,
    )
