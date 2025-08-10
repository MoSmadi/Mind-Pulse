"""
commands/monitor.py
-------------------
Passive harmful-behavior detection for MindPulse.

What this file does:
- Aggregates a user's rapid-fire messages into a single "burst" (debounce).
- Builds conversation context (recent ~15 lines) from the same channel/thread.
- Classifies harm via centralized AI (core.ai.ai.classify_harm).
- Sends a short, empathetic coaching DM in the correct language (ai.coaching_tip).
- Respects a per-user DM cooldown.
- Provides a multilingual heuristic fallback (EN/AR) with fuzzy matching and
  optional keyword extensions via environment variables.

Environment (see core/config.py for common flags you already set):
- HARM_DEBOUNCE_SECONDS        (float, default 1.2)
- HARM_MAX_BURST_SECONDS       (float, default 8.0)
- HARM_MAX_COMBINED_CHARS      (int,   default 500)
- HARM_DM_COOLDOWN_SECONDS     (int,   default 600)
- HARM_DETECTOR                ("azure" | "heuristic" | "hybrid")
- HARM_SEVERITY_MIN            ("low" | "medium" | "high")
- HARM_DEBUG                   ("true" | "false")
- HARM_EXTRA_EN                (comma-separated extra EN keywords; optional)
- HARM_EXTRA_AR                (comma-separated extra AR keywords; optional)
"""

from __future__ import annotations
import re
import os
import time
import asyncio
import discord
from typing import Dict, List
from difflib import SequenceMatcher

from core.ai import ai                 # centralized AI gateway
from core.config import cfg            # single source of truth for harm config
from core.context import ctx_store     # recent conversation window
from core.utils import env_float, env_int, env_csv, normalize_arabic, dearabizi

# Tunables (env overrides)
DEBOUNCE_SECONDS   = env_float("HARM_DEBOUNCE_SECONDS", 1.2)    # quiet period to end burst
MAX_BURST_SECONDS  = env_float("HARM_MAX_BURST_SECONDS", 8.0)   # safety cap
MAX_COMBINED_CHARS = env_int("HARM_MAX_COMBINED_CHARS", 500)    # avoid huge prompts
COOLDOWN_SECONDS   = env_int("HARM_DM_COOLDOWN_SECONDS", 600)   # per-user coaching DM cooldown

# Lightweight heuristic fallback
# --- Heuristic patterns/lexicon (EN + AR dialect + Arabizi) ---

EN_KEYWORDS = {
    "idiot","stupid","moron","dumb","useless","trash","garbage","loser","disgusting",
    "worthless","shut up","kill yourself","wtf","fat","ugly","clown","jerk","bad","worst","pathetic"
} | set(env_csv("HARM_EXTRA_EN"))

# Standard MSA insults + common dialect intensifiers
AR_KEYWORDS = {
    "اخرس","اسكت","كلب","زباله","زبالة","قذر","تفو","تافه","غبي","حقير","احمق","أحمق","كسول","قبيح",
    "سيء","سيئ","اسوء","أسوأ","سخيف","حيوان","انقلع","برا","بره","اختفي","ولك"
} | set(env_csv("HARM_EXTRA_AR"))

# English direct “you are …”
EN_DIRECT_RE = re.compile(
    r"\b(?:(?:hey\s+)?(?:@?\w+)\s+)?(?:you|u|ur|you're|youre)\s+(?:are\s+)?(?:so\s+|such\s+a\s+)?([a-z\-]{2,}\s*){1,4}\b",
    re.I,
)

# Arabic direct forms & colloquial commands:
# - انت/إنت ... <insult>
# - starts with a name then a command (خلص|رد|انقلع...)
# - “رد ع/على <اسم>”  (reply to me) in aggressive imperative usage
AR_DIRECT_RE = re.compile(
    r"(?:(?:^|\s)(?:انت|إنت)\s+[^.!?]*\b(غبي|تافه|كلب|قذر|زباله|زبالة|حقير|قبيح|كسول|سيئ|سيء|أسوأ|اسوء|سخيف)\b)"
    r"|(?:(?:^[\u0621-\u064A]{2,}\s+)(?:خلص|رد|انقلع|برا|بره))"
    r"|(?:\b(?:رد)\s+(?:ع|على)\s+[\u0621-\u064A]{2,})"
)
AR_DIALECT_ENABLED = (os.getenv("AR_DIALECT_ENABLED", "true").strip().lower() in {"1","true","yes","y","on"})


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(a=a.lower(), b=b.lower()).ratio()

def _heuristic_harmful(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False

    # Base forms
    tl = t.lower()

    # Arabic normalization + Arabizi handling
    if AR_DIALECT_ENABLED:
        t_arz  = dearabizi(t)                 # rd 3alay -> رد علي
        t_norm = normalize_arabic(t_arz)      # unify أ/إ/آ..., remove tashkeel/tatweel, collapse repeats
    else:
        t_norm = t

    # 1) Direct insult patterns (English / Arabic)
    if EN_DIRECT_RE.search(tl):
        return True
    if AR_DIALECT_ENABLED and AR_DIRECT_RE.search(t_norm):
        return True

    # 2) Keyword presence (anywhere) — check normalized Arabic too
    if any(k in tl for k in EN_KEYWORDS):
        return True
    if AR_DIALECT_ENABLED and any(k in t_norm for k in AR_KEYWORDS):
        return True

    # 3) Fuzzy catch for typos like "vey bad", "stubid"
    for token in re.findall(r"[a-z]{3,}", tl):
        if any(_similar(token, k) >= 0.82 for k in EN_KEYWORDS):
            return True

    return False

def _severity_rank(sev: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get((sev or "").lower(), 0)

def _passes_policy(harm: dict) -> bool:
    return harm.get("is_harmful") and _severity_rank(harm.get("severity", "low")) >= _severity_rank(cfg.harm_severity_min)

# Burst buffer (per user/channel)
class _Burst:
    __slots__ = ("first_ts", "last_ts", "parts", "task")
    def __init__(self):
        import time
        now = time.time()
        self.first_ts = now
        self.last_ts = now
        self.parts: List[str] = []
        self.task: asyncio.Task | None = None

_BUFFERS: Dict[tuple, _Burst] = {}
_COOLDOWN: Dict[str, float] = {}

def _key(msg: discord.Message) -> tuple:
    gid = msg.guild.id if msg.guild else 0
    return (gid, msg.channel.id, msg.author.id)

def _append(key: tuple, text: str):
    b = _BUFFERS.get(key)
    now = time.time()
    if b is None:
        b = _Burst()
        _BUFFERS[key] = b
    b.last_ts = now
    if text:
        if len(text) > MAX_COMBINED_CHARS:
            text = text[:MAX_COMBINED_CHARS]
        b.parts.append(text)

def _combine(b: _Burst) -> str:
    s = " ".join(b.parts).strip()
    return s[:MAX_COMBINED_CHARS] if len(s) > MAX_COMBINED_CHARS else s

def _can_dm(user_id: str) -> bool:
    now = time.time()
    last = _COOLDOWN.get(user_id, 0)
    if now - last >= COOLDOWN_SECONDS:
        _COOLDOWN[user_id] = now
        return True
    return False

async def _process_after_delay(key: tuple, msg: discord.Message):
    b = _BUFFERS.get(key)
    if not b:
        return

    # Wait for a quiet period; cap total burst length
    while True:
        await asyncio.sleep(0.1)
        if time.time() - b.last_ts >= DEBOUNCE_SECONDS:
            break
        if time.time() - b.first_ts >= MAX_BURST_SECONDS:
            break

    # Pop this burst (prevent double-processing)
    b = _BUFFERS.pop(key, None)
    if not b:
        return

    # Build conversation context (recent lines from same channel)
    window = ctx_store.window(msg.guild.id if msg.guild else None, msg.channel.id, limit=15)
    ctx_lines: list[str] = []
    for m in window:
        who = "You" if m.author_id == msg.author.id else "Other"
        line = (m.content or "").strip().replace("\n", " ")
        if len(line) > 200:
            line = line[:200] + "…"
        ctx_lines.append(f"{who}: {line}")

    text = _combine(b)
    if not text:
        return

    # Classify harm (centralized). Optionally fall back to heuristics in hybrid mode.
    harm = {"is_harmful": False, "severity": "low", "language": "und"}
    try:
        if cfg.harm_detector in ("azure", "hybrid"):
            harm = await asyncio.to_thread(ai.classify_harm, text, ctx_lines)
    except Exception as e:
        if cfg.harm_debug:
            print("harm classify error:", e)

    if cfg.harm_detector in ("heuristic", "hybrid"):
        if not harm.get("is_harmful") and _heuristic_harmful(text):
            harm = {"is_harmful": True, "severity": "medium", "language": "und", "reason": "keyword"}

    if cfg.harm_debug:
        print("[HARM][BURST]", {"text": text, "decision": harm})

    if not _passes_policy(harm):
        return

    # DM with cooldown (avoid spamming users)
    uid = str(msg.author.id)
    if not _can_dm(uid):
        if cfg.harm_debug:
            print("[HARM] cooldown active; skipping DM")
        return

    try:
        tip = await asyncio.to_thread(ai.coaching_tip, text, harm.get("language"))
        await msg.author.send(
            "🧘 **Quick check-in**\n\n"
            f"💬 *\"{text}\"*\n\n"
            f"{tip}\n\n"
            "A short pause can help a lot. You’ve got this 💙"
        )
        if cfg.harm_debug:
            print("[HARM] DM sent to", uid)
    except Exception as e:
        print("❌ Couldn’t DM calming tip:", e)

# Public entry (called from bot.on_message)
async def detect_and_handle_harmful(message: discord.Message) -> None:
    """Collect per-user bursts then schedule classification + DM."""
    if not message.content or message.author.bot:
        return

    key = _key(message)
    _append(key, message.content)

    # cancel previous pending task for this burst key, then schedule new one
    b = _BUFFERS[key]
    if b.task and not b.task.done():
        b.task.cancel()
    b.task = asyncio.create_task(_process_after_delay(key, message))
