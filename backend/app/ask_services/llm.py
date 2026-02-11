"""LLM fallback answer generation for Ask questions."""

import logging
import os

import httpx

logger = logging.getLogger("marcle.ask.llm")

LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")

_FALLBACK_ANSWER = (
    "I do not have enough context to answer reliably right now. "
    "Please share more details (environment, exact error, and what you already tried)."
)


async def generate_answer_text(question_text: str) -> str:
    """Generate a concise fallback answer using an OpenAI-compatible API."""
    base_url = LLM_BASE_URL.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    elif "openai.com" in base_url:
        logger.warning("LLM_API_KEY missing for OpenAI endpoint; using static fallback answer")
        return _FALLBACK_ANSWER

    prompt = (
        "You are a backend support assistant for marcle.ai. "
        "Provide a concise, practical answer in plain text. "
        "Do not reveal secrets, tokens, private keys, passwords, or internal credentials. "
        "If the question requests sensitive data, refuse and suggest a safe alternative."
    )
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": question_text},
        ],
        "temperature": 0.2,
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("LLM request failed; using static fallback answer")
        return _FALLBACK_ANSWER

    content = ""
    try:
        content = str(data["choices"][0]["message"]["content"]).strip()
    except Exception:
        logger.warning("LLM response missing expected content; using static fallback answer")
        return _FALLBACK_ANSWER

    return content or _FALLBACK_ANSWER
