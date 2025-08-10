"""
commands/summary.py
-------------------
Handles the /weekly flow:
- Builds the user's weekly report (off the event loop).
- Sends the report privately via DM, chunked under Discord limits.
- Optionally attaches the pie chart image.
- Optionally reacts on the original message and/or deletes it (for cleanliness).

All analytics come from core/analyzer.generate_weekly_report.
This module should NOT do any AI prompting (kept in core/ai.py).
"""

from __future__ import annotations
import os
import asyncio
import discord
from typing import Iterable, Optional

from core.analyzer import generate_weekly_report
from core.utils import env_bool, env_int

REACTION_ON_PRIVATE_ACTION = env_bool("REACTION_ON_PRIVATE_ACTION", True)
DELETE_COMMAND_AFTER_DM    = env_bool("DELETE_COMMAND_AFTER_DM", False)
DM_MAX_CHARS               = env_int("DM_MAX_CHARS", 1900)
DM_ATTACH_CHART            = env_bool("DM_ATTACH_CHART", True)
DM_RETRY_COUNT             = env_int("DM_RETRY_COUNT", 2)
DM_RETRY_DELAY_MS          = env_int("DM_RETRY_DELAY_MS", 300)

def _chunk_text(s: str, limit: int = DM_MAX_CHARS) -> Iterable[str]:
    """Yield message-safe chunks under the Discord hard cap (~2000)."""
    s = s or ""
    while s:
        yield s[:limit]
        s = s[limit:]

async def _dm_with_retries(
    user: discord.User | discord.Member,
    content: Optional[str] = None,
    file: Optional[discord.File] = None,
    retry_count: int = DM_RETRY_COUNT,
    retry_delay_ms: int = DM_RETRY_DELAY_MS,
) -> bool:
    """
    Try to DM a user with optional file attachment, with small retries.
    Returns True if any attempt succeeds, else False.
    """
    attempts = 0
    while True:
        try:
            await user.send(content=content, file=file)
            return True
        except discord.Forbidden:
            return False
        except discord.HTTPException:
            attempts += 1
            if attempts > retry_count:
                return False
            await asyncio.sleep(retry_delay_ms / 1000)
        except Exception:
            attempts += 1
            if attempts > retry_count:
                return False
            await asyncio.sleep(retry_delay_ms / 1000)

async def handle_weekly_command(message: discord.Message, user_id: str):
    """
    Build the weekly report in a worker thread, then DM it to the author in chunks.
    - If DM fails (closed), we fail silently (channel remains clean).
    - If configured, adds a 📬 reaction to acknowledge; optionally deletes the trigger message.
    """
    # 1) Build report off the event loop
    report_text, chart_path = await asyncio.to_thread(generate_weekly_report, user_id)

    # 2) Send first chunk, possibly with chart
    try:
        chunks = list(_chunk_text(report_text))
        if not chunks:
            chunks = ["(No data)"]

        sent_any = False

        # attach chart only once, on the first chunk (if allowed & exists)
        file_obj: Optional[discord.File] = None
        try:
            if DM_ATTACH_CHART and chart_path and os.path.exists(chart_path):
                file_obj = discord.File(chart_path)
        except Exception:
            file_obj = None  # if file reading fails, just skip attachment

        sent_any = await _dm_with_retries(message.author, content=chunks[0], file=file_obj)

        # remaining chunks (no file)
        if sent_any and len(chunks) > 1:
            for part in chunks[1:]:
                await _dm_with_retries(message.author, content=part, file=None)

        # 3) Channel hygiene (reaction/delete)
        if REACTION_ON_PRIVATE_ACTION:
            try:
                await message.add_reaction("📬" if sent_any else "❌")
            except Exception:
                pass

        if sent_any and DELETE_COMMAND_AFTER_DM and message.guild:
            me = message.guild.me
            if me and message.channel.permissions_for(me).manage_messages:
                try:
                    await message.delete()
                except Exception:
                    pass

    except Exception as e:
        try:
            await message.add_reaction("❌")
        except Exception:
            pass
        print("DM error:", e)
