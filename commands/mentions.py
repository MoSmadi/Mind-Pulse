# commands/mentions.py
"""
/mentions date:<YYYY-MM-DD|today|yesterday>

Collects messages on a local calendar day that mentioned YOU in any of these ways:
  • direct @you
  • @everyone / @here
  • a role mention you belong to
  • (optional) plain‑text name match (display/global/username) with wordish boundaries

Output:
  • Rich embeds grouped by channel; each row shows local time, badges, your response status,
    an excerpt, and a jump link. Ephemeral only. Falls back to compact text on embed errors.

Env (optional):
  MENTIONS_TZ=Asia/Hebron
  MENTIONS_MAX_RESULTS=50
  MENTIONS_PER_CHANNEL_LIMIT=300
  MENTIONS_REACTION_LOOKUP_LIMIT=50
  MENTIONS_REPLY_LOOKUP_LIMIT=150
  MENTIONS_ALLOW_NAME_MATCH=true
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import date
from typing import List, Tuple, Optional

import discord

from core.utils import (
    local_day_bounds_utc,
    parse_local_day,
    format_local_hm,
    short,
    chunk_by_len,
)

# -------------------------
# Config knobs (from .env)
# -------------------------
MENTIONS_TZ = os.getenv("MENTIONS_TZ", "Asia/Hebron").strip()
MENTIONS_MAX_RESULTS = int(os.getenv("MENTIONS_MAX_RESULTS", "50"))
MENTIONS_PER_CHANNEL_LIMIT = int(os.getenv("MENTIONS_PER_CHANNEL_LIMIT", "300"))
MENTIONS_REACTION_LOOKUP_LIMIT = int(os.getenv("MENTIONS_REACTION_LOOKUP_LIMIT", "50"))
MENTIONS_REPLY_LOOKUP_LIMIT = int(os.getenv("MENTIONS_REPLY_LOOKUP_LIMIT", "150"))
MENTIONS_ALLOW_NAME_MATCH = os.getenv("MENTIONS_ALLOW_NAME_MATCH", "true").strip().lower() in {
    "1", "true", "yes", "y", "on"
}

_JUMP = "https://discord.com/channels/{gid}/{cid}/{mid}"

# -------------------------
# Badges & chips
# -------------------------
BADGE_EMOJI = {
    "@you": "🧍",
    "@here": "📣",
    "@everyone": "📢",
    "role": "🏷️",
    "name": "🔎",
}
RESP_EMOJI = {
    "reply": "💬",
    "thread": "🧵",
    "reaction": "👍",
}


# -------------------------
# Helpers: response checks
# -------------------------
async def _user_reacted_to(msg: discord.Message, user: discord.abc.User) -> bool:
    """Did YOU react to this message? (bounded scan per reaction)"""
    try:
        for reaction in msg.reactions:
            async for u in reaction.users(limit=MENTIONS_REACTION_LOOKUP_LIMIT):
                if u.id == user.id:
                    return True
    except Exception:
        pass
    return False


async def _user_replied_to(channel: discord.abc.Messageable, msg: discord.Message, user: discord.abc.User) -> bool:
    """Did YOU reply to THIS message in the same channel (not thread)?"""
    try:
        async for m in channel.history(after=msg.created_at, limit=MENTIONS_REPLY_LOOKUP_LIMIT, oldest_first=True):
            if m.author.id != user.id:
                continue
            if m.reference and m.reference.message_id == msg.id:
                return True
    except Exception:
        pass
    return False


async def _user_posted_in_thread(msg: discord.Message, user: discord.abc.User) -> bool:
    """Did YOU post in the thread attached to THIS message?"""
    try:
        th = getattr(msg, "thread", None)
        if not th:
            return False
        async for m in th.history(limit=MENTIONS_REPLY_LOOKUP_LIMIT, oldest_first=True):
            if m.author.id == user.id:
                return True
    except Exception:
        pass
    return False


# -------------------------
# Helpers: mention detection
# -------------------------
def _explicit_user_mention(msg: discord.Message, me: discord.abc.User) -> bool:
    """True if the message explicitly mentions you as a user."""
    try:
        if me in getattr(msg, "mentions", []):
            return True
    except Exception:
        pass
    c = (msg.content or "")
    return f"<@{me.id}>" in c or f"<@!{me.id}>" in c


def _everyone_or_here(msg: discord.Message) -> Optional[str]:
    """Return '@everyone' or '@here' if present/visible, else None."""
    if getattr(msg, "mention_everyone", False):
        # Discord doesn't separate here vs everyone in a flag; inspect content:
        return "@here" if "@here" in (msg.content or "") else "@everyone"
    return None


def _role_mentions_for_me(msg: discord.Message, me: discord.Member | discord.User) -> list[str]:
    """Return role names that were mentioned AND that you belong to."""
    out: list[str] = []
    try:
        if isinstance(me, discord.Member):
            my_roles = {r.id for r in me.roles}
            for r in getattr(msg, "role_mentions", []):
                if r.id in my_roles:
                    out.append(f"@{r.name}")
    except Exception:
        pass
    return out


def _plain_name_match(msg: discord.Message, me: discord.Member | discord.User) -> bool:
    """
    Optional: plain-text name match with safe boundaries (reduces false positives).
    Checks display name, global name, and username (longest first).
    """
    if not MENTIONS_ALLOW_NAME_MATCH:
        return False

    content = (msg.content or "")
    names: list[str] = []
    if isinstance(me, discord.Member) and me.display_name:
        names.append(me.display_name)
    gn = getattr(me, "global_name", None)
    if gn:
        names.append(gn)
    if me.name:
        names.append(me.name)

    seen = set()
    candidates = []
    for n in sorted(names, key=lambda s: len(s or ""), reverse=True):
        n = (n or "").strip()
        if not n or n.lower() in seen or len(n) < 3:
            continue
        seen.add(n.lower())
        candidates.append(n)

    for n in candidates:
        # Use a loose boundary: start/end or common separators/punct
        esc = re.escape(n)
        pat = rf"(^|[\s,.;:!?()<>@#\[\]{{}}\"'`~\\/|-]){esc}($|[\s,.;:!?()<>@#\[\]{{}}\"'`~\\/|-])"
        if re.search(pat, content, flags=re.IGNORECASE):
            return True
    return False


def _counts_as_mention(msg: discord.Message, me: discord.Member | discord.User) -> tuple[bool, list[str]]:
    """
    Include this message if ANY of:
      - direct @you
      - @everyone/@here
      - a role mention you belong to
      - (optional) plain‑text name match
    Returns (include, badges[])
    """
    badges: list[str] = []

    if _explicit_user_mention(msg, me):
        badges.append("@you")

    eh = _everyone_or_here(msg)
    if eh:
        badges.append(eh)

    for rn in _role_mentions_for_me(msg, me):
        badges.append(rn)  # role badges are literal like @Engineers

    if _plain_name_match(msg, me):
        badges.append("name")

    return (len(badges) > 0, badges)


# -------------------------
# Collector
# -------------------------
async def collect_mentions_for_day(
    guild: discord.Guild,
    me: discord.Member | discord.User,
    the_day_local: date,
    max_results: int = MENTIONS_MAX_RESULTS
) -> list[tuple[discord.Message, list[str], str]]:
    """
    Scan readable channels and return up to max_results of:
        (message, badges[], response_status)
    """
    start_utc, end_utc = local_day_bounds_utc(the_day_local, MENTIONS_TZ)
    out: list[tuple[discord.Message, list[str], str]] = []

    for ch in guild.text_channels:
        perms = ch.permissions_for(guild.me)
        if not (perms.read_messages and perms.read_message_history):
            continue
        try:
            async for msg in ch.history(after=start_utc, before=end_utc, limit=MENTIONS_PER_CHANNEL_LIMIT, oldest_first=True):
                if not msg or not msg.content:
                    continue

                include, badges = _counts_as_mention(msg, me)
                if not include:
                    continue

                # annotate whether YOU responded (do not filter out)
                reacted = await _user_reacted_to(msg, me)
                replied = await _user_replied_to(ch, msg, me)
                in_thread = await _user_posted_in_thread(msg, me)

                parts = []
                if replied:
                    parts.append("reply")
                if in_thread:
                    parts.append("thread")
                if reacted:
                    parts.append("reaction")
                status = "responded: " + "/".join(parts) if parts else "no response yet"

                out.append((msg, badges, status))
                if len(out) >= max_results:
                    return out
        except Exception:
            # Skip channels we can't scan or that error out
            continue

    return out


# -------------------------
# Formatting (embeds + fallback)
# -------------------------
def _chip(text: str, emoji: str | None = None) -> str:
    return f"`{emoji} {text}`" if emoji else f"`{text}`"


def _badge_chips(badges: list[str]) -> str:
    chips = []
    for b in badges:
        if b.startswith("@") and b not in BADGE_EMOJI:
            chips.append(_chip(b, BADGE_EMOJI.get("role")))
        else:
            chips.append(_chip(b, BADGE_EMOJI.get(b)))
    return " ".join(chips) if chips else "`[mention]`"


def _response_chips(status: str) -> str:
    if status.startswith("responded: "):
        bits = status.replace("responded: ", "").split("/")
        return " ".join(_chip(x, RESP_EMOJI.get(x)) for x in bits if x)
    return _chip("no response", "⏳")


def _group_by_channel(triples: list[tuple[discord.Message, list[str], str]]):
    groups = defaultdict(list)
    for msg, badges, status in triples:
        groups[msg.channel].append((msg, badges, status))
    # sort inside each channel by time ascending
    for ch in groups:
        groups[ch].sort(key=lambda t: t[0].created_at)
    return groups


def _build_channel_embed(
    guild: discord.Guild,
    channel: discord.TextChannel,
    rows,
    the_day_local: date,
    tz_name: str
) -> discord.Embed:
    title = f"#{channel.name} — mentions on {the_day_local.isoformat()}"
    em = discord.Embed(title=title, color=0x5865F2)  # Discord blurple
    em.set_footer(text=f"{guild.name} • local tz: {tz_name}")

    lines = []
    for msg, badges, status in rows:
        hhmm = format_local_hm(msg.created_at, tz_name)
        link = _JUMP.format(gid=guild.id, cid=channel.id, mid=msg.id)
        excerpt = short(msg.content, 110)
        chips = _badge_chips(badges)
        resp = _response_chips(status)
        lines.append(f"**{hhmm}** • {chips} • {resp}\n“{excerpt}” — [Jump]({link})")

    desc = "\n\n".join(lines)
    # Discord embed description max ~4096 chars; trim softly
    if len(desc) > 4000:
        desc = desc[:3980] + "…"
    em.description = desc
    return em


def _format_mentions_embeds(
    guild: discord.Guild,
    triples: list[tuple[discord.Message, list[str], str]],
    the_day_local: date,
    tz_name: str
) -> list[discord.Embed]:
    if not triples:
        em = discord.Embed(
            title=f"No mentions for {the_day_local.isoformat()}",
            description="Enjoy the quiet ✨",
            color=0x2ECC71,
        )
        em.set_footer(text=f"{guild.name} • local tz: {tz_name}")
        return [em]

    groups = _group_by_channel(triples)
    embeds: list[discord.Embed] = []
    for channel, rows in groups.items():
        embeds.append(_build_channel_embed(guild, channel, rows, the_day_local, tz_name))
    return embeds


# Text fallback (kept simple & compact)
def _format_mentions_ephemeral(
    guild: discord.Guild,
    triples: list[tuple[discord.Message, list[str], str]],
    the_day_local: date
) -> str:
    if not triples:
        return f"📭 No mentions for **{the_day_local.isoformat()}**."
    lines = [f"🔔 Mentions for {the_day_local.isoformat()} (max {MENTIONS_MAX_RESULTS})"]
    for msg, badges, status in triples:
        link = _JUMP.format(gid=guild.id, cid=msg.channel.id, mid=msg.id)
        excerpt = short(msg.content, 110)
        ch_name = f"#{getattr(msg.channel, 'name', 'DM')}"
        hhmm = format_local_hm(msg.created_at, MENTIONS_TZ)
        badge_str = " ".join(badges) if badges else "[mention]"
        lines.append(f"• {hhmm} {ch_name} — {badge_str} — {status} — “{excerpt}” — <{link}>")
    return "\n".join(lines)


# -------------------------
# Entrypoint from bot.py
# -------------------------
async def run_mentions_command(
    interaction: discord.Interaction,
    date_text: Optional[str] = None
) -> None:
    """Called by the slash command in bot.py. Builds embeds, with safe ack/fallback."""
    # Acknowledge quickly; avoid 10062 races
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
    except Exception:
        pass

    if not interaction.guild:
        try:
            await interaction.followup.send("Run this in a server so I can scan your channels.", ephemeral=True)
        except Exception:
            return
        return

    the_day = parse_local_day(date_text, MENTIONS_TZ)  # None/bad → today
    triples = await collect_mentions_for_day(interaction.guild, interaction.user, the_day)

    # Prefer rich embeds; paginate by 10 embeds per message
    try:
        embeds = _format_mentions_embeds(interaction.guild, triples, the_day, MENTIONS_TZ)

        page: list[discord.Embed] = []
        sent_any = False
        for em in embeds:
            page.append(em)
            if len(page) == 10:
                await interaction.followup.send(embeds=page, ephemeral=True)
                page = []
                sent_any = True
        if page:
            await interaction.followup.send(embeds=page, ephemeral=True)
            sent_any = True

        if not sent_any:
            await interaction.followup.send("📭 No mentions found.", ephemeral=True)
        return

    except Exception:
        # Fallback to simple text if embed sending failed
        text = _format_mentions_ephemeral(interaction.guild, triples, the_day)
        for chunk in chunk_by_len(text, 1900):
            try:
                await interaction.followup.send(chunk, ephemeral=True)
            except Exception:
                break
