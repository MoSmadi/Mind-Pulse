"""
core/context.py
---------------
Lightweight rolling message store per (guild, channel) to build recent context
windows for AI (sentiment + harmful detection). Keeps memory only in runtime.
"""

from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple, List, Optional

@dataclass
class Msg:
    author_id: int
    content: str

class _ContextStore:
    def __init__(self, max_per_channel: int = 50):
        self.max_per_channel = max_per_channel
        self._buf: Dict[Tuple[int|None, int], Deque[Msg]] = defaultdict(lambda: deque(maxlen=self.max_per_channel))

    def add(self, guild_id: int | None, channel_id: int, author_id: int, content: str):
        key = (guild_id, channel_id)
        self._buf[key].append(Msg(author_id=author_id, content=content))

    def window(self, guild_id: int | None, channel_id: int, limit: int = 15) -> List[Msg]:
        key = (guild_id, channel_id)
        q = self._buf.get(key)
        if not q:
            return []
        # return most recent 'limit' messages
        return list(q)[-limit:]

ctx_store = _ContextStore()
