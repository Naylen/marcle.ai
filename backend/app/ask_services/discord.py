"""Discord webhook integration for Ask app."""

from dataclasses import dataclass
import logging
import os
import urllib.parse

import httpx

logger = logging.getLogger("marcle.ask.discord")

DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")
BASE_PUBLIC_URL: str = os.getenv("BASE_PUBLIC_URL", "")
DISCORD_BOT_TOKEN: str = os.getenv("DISCORD_BOT_TOKEN", "")
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
        "name": f"Question #{question_id}",
        "auto_archive_duration": 1440,
    }
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
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


async def post_question_to_discord(
    *,
    question_id: int,
    user_name: str,
    user_email: str,
    question_text: str,
) -> DiscordQuestionPostResult:
    """Post a new question notification to Discord and return message metadata."""
    if not DISCORD_WEBHOOK_URL:
        logger.warning("DISCORD_WEBHOOK_URL not set; skipping webhook post")
        return DiscordQuestionPostResult(delivered=False)

    answer_endpoint = (
        f"{BASE_PUBLIC_URL.rstrip('/')}/api/ask/answers"
        if BASE_PUBLIC_URL.strip()
        else "/api/ask/answers"
    )

    # Build a rich embed for Discord
    embed = {
        "title": f"New Question #{question_id}",
        "color": 0x5865F2,  # Discord blurple
        "fields": [
            {"name": "From", "value": f"{user_name} ({user_email})", "inline": True},
            {"name": "Question ID", "value": str(question_id), "inline": True},
            {"name": "Question", "value": question_text[:1024]},  # Discord field limit
            {
                "name": "How to Answer",
                "value": (
                    "Send a POST to the answer endpoint:\n"
                    "```\n"
                    f"POST {answer_endpoint}\n"
                    "Headers: X-Webhook-Secret: <ASK_ANSWER_WEBHOOK_SECRET>\n"
                    "Body: {\"question_id\": " + str(question_id) + ", \"answer_text\": \"Your answer here\"}\n"
                    "```"
                ),
            },
        ],
        "footer": {"text": "marcle.ai Ask"},
    }

    payload = {
        "embeds": [embed],
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_webhook_wait_url(DISCORD_WEBHOOK_URL), json=payload)
            resp.raise_for_status()
            body = resp.json() if resp.content else {}
            message_id = str(body["id"]) if body.get("id") else None
            channel_id = str(body["channel_id"]) if body.get("channel_id") else None
            guild_id = str(body["guild_id"]) if body.get("guild_id") else None
            thread_id = None
            if channel_id and message_id:
                thread_id = await _create_discord_thread(
                    client=client,
                    channel_id=channel_id,
                    message_id=message_id,
                    question_id=question_id,
                )
            logger.info("Discord webhook sent for question_id=%d", question_id)
            return DiscordQuestionPostResult(
                delivered=True,
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
                thread_id=thread_id,
            )
    except Exception:
        logger.exception("Failed to send Discord webhook for question_id=%d", question_id)
        return DiscordQuestionPostResult(delivered=False)
