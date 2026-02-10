"""Discord webhook integration for Ask app."""

import logging
import os

import httpx

logger = logging.getLogger("marcle.ask.discord")

DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")
BASE_PUBLIC_URL: str = os.getenv("BASE_PUBLIC_URL", "")


async def post_question_to_discord(
    *,
    question_id: int,
    user_name: str,
    user_email: str,
    question_text: str,
) -> bool:
    """Post a new question notification to Discord. Returns True on success."""
    if not DISCORD_WEBHOOK_URL:
        logger.warning("DISCORD_WEBHOOK_URL not set; skipping webhook post")
        return False

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
            resp = await client.post(DISCORD_WEBHOOK_URL, json=payload)
            resp.raise_for_status()
            logger.info("Discord webhook sent for question_id=%d", question_id)
            return True
    except Exception:
        logger.exception("Failed to send Discord webhook for question_id=%d", question_id)
        return False
