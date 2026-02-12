"""Discord bot client for Ask human-answer ingestion and answer posting."""

import asyncio
import logging
import os
from typing import Awaitable, Callable

import httpx

from app.env_utils import get_env

try:
    import discord
except Exception:  # pragma: no cover - optional dependency at runtime
    discord = None

logger = logging.getLogger("marcle.ask.discord.bot")

DISCORD_BOT_TOKEN: str = get_env("DISCORD_BOT_TOKEN", "")
DISCORD_SUPPORT_ROLE_ID: str = os.getenv("DISCORD_SUPPORT_ROLE_ID", "")
DISCORD_API_BASE: str = os.getenv("DISCORD_API_BASE", "https://discord.com/api/v10")

HumanAnswerCallback = Callable[[dict[str, str]], Awaitable[None]]

_client: "AskDiscordClient | None" = None
_client_task: asyncio.Task | None = None


def _support_role_id_int() -> int | None:
    value = DISCORD_SUPPORT_ROLE_ID.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        logger.warning("DISCORD_SUPPORT_ROLE_ID is invalid: %r", value)
        return None


class AskDiscordClient(discord.Client):  # type: ignore[misc]
    def __init__(self, on_human_answer: HumanAnswerCallback, support_role_id: int):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)
        self._on_human_answer = on_human_answer
        self._support_role_id = support_role_id

    async def on_ready(self):
        logger.info("Ask Discord bot connected as %s", getattr(self.user, "name", "unknown"))

    async def on_message(self, message):
        if getattr(message.author, "bot", False):
            return
        if self._support_role_id <= 0:
            return
        if message.guild is None:
            return

        member = message.author if isinstance(message.author, discord.Member) else None
        if member is None:
            try:
                member = await message.guild.fetch_member(message.author.id)
            except Exception:
                logger.warning("Could not fetch member for discord author=%s", getattr(message.author, "id", "unknown"))
                return

        if all(role.id != self._support_role_id for role in getattr(member, "roles", [])):
            return

        is_thread = isinstance(message.channel, discord.Thread)
        reference = getattr(message, "reference", None)
        reply_to_message_id = (
            str(reference.message_id)
            if reference is not None and getattr(reference, "message_id", None)
            else ""
        )
        if not is_thread and not reply_to_message_id:
            return

        if is_thread:
            channel_id = str(getattr(message.channel, "parent_id", "") or message.channel.id)
            thread_id = str(message.channel.id)
        else:
            channel_id = str(message.channel.id)
            thread_id = ""

        if not (message.content or "").strip():
            return

        payload = {
            "guild_id": str(message.guild.id),
            "channel_id": channel_id,
            "thread_id": thread_id,
            "message_id": str(message.id),
            "reply_to_message_id": reply_to_message_id,
            "content": message.content or "",
            "author_id": str(member.id),
            "author_name": getattr(member, "display_name", None) or getattr(message.author, "name", ""),
            "timestamp": message.created_at.isoformat() if getattr(message, "created_at", None) else "",
        }
        await self._on_human_answer(payload)


async def start_discord_client(on_human_answer: HumanAnswerCallback) -> None:
    """Start Discord bot listener for Ask human answers."""
    global _client, _client_task
    if _client_task is not None and not _client_task.done():
        return
    if not DISCORD_BOT_TOKEN:
        logger.info("DISCORD_BOT_TOKEN not set; Discord human-answer listener disabled")
        return
    if discord is None:
        logger.warning("discord.py is not installed; Discord human-answer listener disabled")
        return
    support_role_id = _support_role_id_int()
    if support_role_id is None:
        logger.warning("DISCORD_SUPPORT_ROLE_ID not set/invalid; Discord human-answer listener disabled")
        return

    _client = AskDiscordClient(on_human_answer, support_role_id=support_role_id)
    _client_task = asyncio.create_task(_client.start(DISCORD_BOT_TOKEN), name="ask-discord-bot")

    def _handle_done(task: asyncio.Task) -> None:
        global _client_task, _client
        _client_task = None
        _client = None
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.exception("Discord bot task exited with error", exc_info=exc)

    _client_task.add_done_callback(_handle_done)


async def stop_discord_client() -> None:
    """Stop Discord bot listener."""
    global _client, _client_task
    if _client is not None:
        try:
            await _client.close()
        except Exception:
            logger.exception("Error while closing Discord bot client")
    if _client_task is not None:
        _client_task.cancel()
        try:
            await _client_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error while waiting for Discord bot task shutdown")
    _client_task = None
    _client = None


async def post_answer_to_discord(
    *,
    answer_text: str,
    thread_id: str | None = None,
    channel_id: str | None = None,
    reply_to_message_id: str | None = None,
) -> bool:
    """Post an answer into Discord thread or channel reply."""
    if not DISCORD_BOT_TOKEN:
        logger.info("DISCORD_BOT_TOKEN not set; skipping Discord answer post")
        return False
    target_channel = (thread_id or channel_id or "").strip()
    if not target_channel:
        return False

    url = f"{DISCORD_API_BASE.rstrip('/')}/channels/{target_channel}/messages"
    payload: dict[str, object] = {
        "content": answer_text[:1900],
        "allowed_mentions": {"replied_user": False},
    }
    if not thread_id and reply_to_message_id:
        payload["message_reference"] = {"message_id": reply_to_message_id}

    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                logger.warning("Discord answer post failed status=%d body=%s", resp.status_code, resp.text[:300])
                return False
        return True
    except Exception:
        logger.exception("Failed posting answer to Discord")
        return False
