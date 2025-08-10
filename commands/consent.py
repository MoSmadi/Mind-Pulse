"""
commands/consent.py
-------------------
Manages user consent for MindPulse tracking.

Responsibilities:
- Persist a set of consented user IDs in data/consent.json
- Provide simple APIs to add/remove/check consent
- Optional auto-consent for testing via CONSENT_AUTOFILL
"""

from __future__ import annotations
from typing import Set, List
import os
from pathlib import Path

from core.utils import DATA_DIR, load_json, save_json

CONSENT_FILE: Path = DATA_DIR / "consent.json"

def _autofill_ids() -> Set[str]:
    raw = os.getenv("CONSENT_AUTOFILL", "").strip()
    if not raw:
        return set()
    return {tok.strip() for tok in raw.split(",") if tok.strip()}

def _load_file() -> List[str]:
    data = load_json(CONSENT_FILE, default=[], required_type=list)
    return [str(x) for x in data]

def _save_file(ids: Set[str]) -> None:
    # Do not persist env autofill on disk
    explicit_only = set(ids) - _autofill_ids()
    save_json(CONSENT_FILE, sorted(explicit_only))

def load_consents() -> Set[str]:
    ids = set(_load_file())
    ids |= _autofill_ids()
    return ids

def save_consents(consents: Set[str]) -> None:
    _save_file(consents)

def add_consent(user_id: str) -> None:
    c = load_consents()
    c.add(user_id)
    save_consents(c)

def remove_consent(user_id: str) -> None:
    c = load_consents()
    if user_id in c:
        c.remove(user_id)
        save_consents(c)

def has_consented(user_id: str) -> bool:
    return user_id in load_consents()
