"""Discord integration for Ask question posting and thread creation."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import urllib.parse

import httpx

from app.env_utils import get_env
from app.log_redact import httpx_event_hooks

logger = logging.getLogger("marcle.ask.discord")

DISCORD_WEBHOOK_URL: str = get_env("DISCORD_WEBHOOK_URL", "")
DISCORD_BOT_TOKEN: str = get_env("DISCORD_BOT_TOKEN", "")
DISCORD_ASK_CHANNEL_ID: str = os.getenv("DISCORD_ASK_CHANNEL_ID", "")
DISCORD_GUILD_ID: str = os.getenv("DISCORD_GUILD_ID", "")
DISCORD_API_BASE: str = os.getenv("DISCORD_API_BASE", "https://discord.com/api/v10")


@dataclass
class DiscordQuestionPostResult:
    delivered: bool
    guild_id: str | None = None
    channel_id: str | None = None
    message_id: str | None = None
    thread_id: str | None = None


def _webhook_wait_url(webhook_url: str) -> str:
    parsed = urllib.parse.urlparse(webhook_url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    query["wait"] = ["true"]
    new_query = urllib.parse.urlencode(query, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


def _bot_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }


def _question_embed(*, question_id: int, user_name: str, user_email: str, question_text: str) -> dict:
    return {
        "title": f"Ask Question #{question_id}",
        "color": 0x5865F2,
        "fields": [
            {"name": "From", "value": f"{user_name} ({user_email})", "inline": True},
            {"name": "Question ID", "value": str(question_id), "inline": True},
            {"name": "Question", "value": question_text[:1024]},
            {"name": "How to answer", "value": "Reply in this thread or reply directly to this message in-channel."},
        ],
        "footer": {"text": "marcle.ai Ask"},
    }


async def _fetch_message_thread_id(
    *,
    client: httpx.AsyncClient,
    channel_id: str,
    message_id: str,
) -> str | None:
    url = f"{DISCORD_API_BASE.rstrip('/')}/channels/{channel_id}/messages/{message_id}"
    try:
        resp = await client.get(url, headers=_bot_headers())
        if resp.status_code >= 400:
            return None
        body = resp.json() if resp.content else {}
        thread = body.get("thread")
        if isinstance(thread, dict) and thread.get("id"):
            return str(thread["id"])
    except Exception:
        logger.exception("Failed fetching Discord message thread metadata channel=%s message=%s", channel_id, message_id)
    return None


async def _create_discord_thread(
    *,
    client: httpx.AsyncClient,
    channel_id: str,
    message_id: str,
    question_id: int,
) -> str | None:
    if not DISCORD_BOT_TOKEN:
        return None
    url = f"{DISCORD_API_BASE.rstrip('/')}/channels/{channel_id}/messages/{message_id}/threads"
    payload = {
        "name": f"Ask #{question_id}",
        "auto_archive_duration": 1440,
    }
    try:
        resp = await client.post(url, json=payload, headers=_bot_headers())
        if resp.status_code >= 400:
            body: dict = {}
            try:
                body = resp.json() if resp.content else {}
            except ValueError:
                body = {}
            if body.get("code") == 160004:
                # Thread already exists for this message. Reuse it.
                return await _fetch_message_thread_id(
                    client=client,
                    channel_id=channel_id,
                    message_id=message_id,
                )
            logger.warning(
                "Failed to create thread for question_id=%d status=%d body=%s",
                question_id,
                resp.status_code,
                resp.text[:300],
            )
            return None
        body = resp.json() if resp.content else {}
        thread_id = body.get("id")
        return str(thread_id) if thread_id else None
    except Exception:
        logger.exception("Failed creating Discord thread for question_id=%d", question_id)
        return None


async def _post_question_via_bot(
    *,
    client: httpx.AsyncClient,
    question_id: int,
    user_name: str,
    user_email: str,
    question_text: str,
) -> DiscordQuestionPostResult:
    url = f"{DISCORD_API_BASE.rstrip('/')}/channels/{DISCORD_ASK_CHANNEL_ID}/messages"
    payload = {
        "content": f"New Ask question #{question_id}",
        "embeds": [
            _question_embed(
                question_id=question_id,
                user_name=user_name,
                user_email=user_email,
                question_text=question_text,
            )
        ],
        "allowed_mentions": {"parse": []},
    }
    resp = await client.post(url, json=payload, headers=_bot_headers())
    if resp.status_code >= 400:
        logger.warning(
            "Failed to post Ask question via bot status=%d body=%s",
            resp.status_code,
            resp.text[:300],
        )
        return DiscordQuestionPostResult(delivered=False)

    body = resp.json() if resp.content else {}
    message_id = str(body.get("id") or "").strip() or None
    channel_id = str(body.get("channel_id") or DISCORD_ASK_CHANNEL_ID).strip() or None
    guild_id = str(body.get("guild_id") or DISCORD_GUILD_ID).strip() or None
    thread_id = None
    if channel_id and message_id:
        thread_id = await _create_discord_thread(
            client=client,
            channel_id=channel_id,
            message_id=message_id,
            question_id=question_id,
        )
    return DiscordQuestionPostResult(
        delivered=bool(message_id),
        guild_id=guild_id,
        channel_id=channel_id,
        message_id=message_id,
        thread_id=thread_id,
    )


async def _post_question_via_webhook(
    *,
    client: httpx.AsyncClient,
    question_id: int,
    user_name: str,
    user_email: str,
    question_text: str,
) -> DiscordQuestionPostResult:
    payload = {
        "embeds": [
            _question_embed(
                question_id=question_id,
                user_name=user_name,
                user_email=user_email,
                question_text=question_text,
            )
        ],
    }
    resp = await client.post(_webhook_wait_url(DISCORD_WEBHOOK_URL), json=payload)
    resp.raise_for_status()
    body = resp.json() if resp.content else {}
    message_id = str(body.get("id") or "").strip() or None
    channel_id = str(body.get("channel_id") or "").strip() or None
    guild_id = str(body.get("guild_id") or DISCORD_GUILD_ID).strip() or None
    thread_id = None
    if DISCORD_BOT_TOKEN and channel_id and message_id:
        thread_id = await _create_discord_thread(
            client=client,
            channel_id=channel_id,
            message_id=message_id,
            question_id=question_id,
        )
    return DiscordQuestionPostResult(
        delivered=bool(message_id),
        guild_id=guild_id,
        channel_id=channel_id,
        message_id=message_id,
        thread_id=thread_id,
    )


async def post_question_to_discord(
    *,
    question_id: int,
    user_name: str,
    user_email: str,
    question_text: str,
) -> DiscordQuestionPostResult:
    """Post a new Ask question and create a per-question thread when possible."""
    async with httpx.AsyncClient(timeout=15.0, event_hooks=httpx_event_hooks()) as client:
        if DISCORD_BOT_TOKEN and DISCORD_ASK_CHANNEL_ID:
            try:
                result = await _post_question_via_bot(
                    client=client,
                    question_id=question_id,
                    user_name=user_name,
                    user_email=user_email,
                    question_text=question_text,
                )
                if result.delivered:
                    logger.info("Discord bot question sent for question_id=%d", question_id)
                    return result
            except Exception:
                logger.exception("Failed posting Ask question via Discord bot for question_id=%d", question_id)

        if DISCORD_WEBHOOK_URL:
            try:
                result = await _post_question_via_webhook(
                    client=client,
                    question_id=question_id,
                    user_name=user_name,
                    user_email=user_email,
                    question_text=question_text,
                )
                logger.info("Discord webhook question sent for question_id=%d", question_id)
                return result
            except Exception:
                logger.exception("Failed posting Ask question via Discord webhook for question_id=%d", question_id)

    logger.warning(
        "Discord question delivery unavailable (need bot+channel or webhook). question_id=%d",
        question_id,
    )
    return DiscordQuestionPostResult(delivered=False)
