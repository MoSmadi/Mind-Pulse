"""
commands/assign.py
------------------
Manager → team membership mapping.

Data shape in data/roles.json:
{
  "<manager_id>": ["<user_id>", "<user_id>", ...],
  ...
}
"""

from __future__ import annotations
from typing import Dict, List, Set
import os
from core.utils import DATA_DIR, load_json, save_json

ROLES_FILE = DATA_DIR / "roles.json"

def _normalize(ids: list[str] | set[str]) -> list[str]:
    return sorted({str(x).strip() for x in ids if str(x).strip()})

def _parse_autofill() -> dict[str, list[str]]:
    raw = os.getenv("ROLES_AUTOFILL", "").strip()
    if not raw:
        return {}
    out: dict[str, list[str]] = {}
    # format: "mgr:uid1,uid2; mgr2:uid3|uid4"
    for grp in raw.split(";"):
        grp = grp.strip()
        if not grp or ":" not in grp:
            continue
        m, users_str = grp.split(":", 1)
        users = [u.strip() for part in users_str.split("|") for u in part.split(",") if u.strip()]
        if m.strip() and users:
            out[str(m.strip())] = _normalize(users)
    return out

def _load_roles() -> dict[str, list[str]]:
    data = load_json(ROLES_FILE, default={}, required_type=dict)
    cleaned: dict[str, list[str]] = {}
    for k, v in (data or {}).items():
        if isinstance(v, list):
            cleaned[str(k)] = _normalize(v)
    # merge ROLES_AUTOFILL non-destructively
    for m, users in _parse_autofill().items():
        cleaned.setdefault(m, [])
        cleaned[m] = _normalize(set(cleaned[m]) | set(users))
    return cleaned

def _save_roles(obj: dict[str, list[str]]) -> None:
    save_json(ROLES_FILE, obj)

def assign_user_to_manager(manager_id: str, user_id: str) -> None:
    roles = _load_roles()
    manager_id = str(manager_id)
    user_id = str(user_id)
    team = roles.get(manager_id, [])
    if user_id not in team:
        team.append(user_id)
    roles[manager_id] = _normalize(team)
    _save_roles(roles)

def get_users_for_manager(manager_id: str) -> list[str]:
    return _load_roles().get(str(manager_id), [])
