"""
core/utils.py
--------------
Project-wide utilities:
- Project paths (ROOT, DATA_DIR, CHARTS_DIR) + ensure_dirs()
- Robust JSON I/O (UTF-8, defaults, optional type checks, atomic writes)
- Tiny env readers (bool/int/float/csv)
- Small time helpers (utcnow_iso, since_days)
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Iterable, Optional, Type
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import json
import re
import os
import tempfile

# -------- Paths --------

ROOT: Path = Path(__file__).resolve().parents[1]
DATA_DIR: Path = ROOT / "data"
CHARTS_DIR: Path = DATA_DIR / "charts"

def ensure_dirs() -> None:
    """Create required folders if missing."""
    for d in (DATA_DIR, CHARTS_DIR):
        d.mkdir(parents=True, exist_ok=True)

# -------- Env helpers --------

def env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}

def env_int(key: str, default: int = 0) -> int:
    v = os.getenv(key)
    if v is None:
        return default
    try:
        return int(v.strip())
    except Exception:
        return default

def env_float(key: str, default: float = 0.0) -> float:
    v = os.getenv(key)
    if v is None:
        return default
    try:
        return float(v.strip())
    except Exception:
        return default

def env_csv(key: str, default: Iterable[str] | None = None) -> list[str]:
    v = os.getenv(key)
    if not v:
        return list(default) if default is not None else []
    return [tok.strip() for tok in v.split(",") if tok.strip()]

# -------- JSON I/O --------

def load_json(path: str | Path, default: Any = None, required_type: Type | tuple[Type, ...] | None = None) -> Any:
    """
    Load JSON (UTF-8). If file is missing/invalid, return `default`.
    If `required_type` is provided and the parsed value isn't that type,
    return `default` instead.
    """
    p = Path(path)
    if not p.exists():
        return default
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if required_type is not None and not isinstance(data, required_type):
            return default
        return data
    except Exception as e:
        print(f"⚠️ load_json warning for {p}: {e}")
        return default

def save_json(path: str | Path, obj: Any, atomic: bool = True) -> None:
    """
    Save JSON (UTF-8). If `atomic` is True, write to a temp file then replace
    to reduce risk of partial/corrupt writes on crashes.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    if not atomic:
        with p.open("w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
        return

    tmp_fd, tmp_path = tempfile.mkstemp(prefix=p.name, dir=str(p.parent))
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, p)  # atomic on most OSes
    except Exception as e:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        raise e

# -------- Time helpers --------

def utcnow_iso() -> str:
    return datetime.utcnow().isoformat()

def since_days(days: int) -> datetime:
    return datetime.utcnow() - timedelta(days=days)


_AR_DIACRITICS_RE = re.compile(r"[\u0617-\u061A\u064B-\u0652]")
_TATWEEL = "\u0640"

_ARABIZI_MAP = str.maketrans({
    "2": "ا",  # often hamza/alif in Arabizi
    "3": "ع",
    "5": "خ",
    "6": "ط",
    "7": "ح",
    "8": "ق",  # sometimes غ/ق; we pick ق for moderation purposes
    "9": "ص",  # sometimes ق/ص; we pick ص for toxicity cues
})

def normalize_arabic(s: str) -> str:
    """
    Normalize Arabic text for robust matching:
    - remove tatweel and diacritics
    - unify letter variants: أ/إ/آ→ا, ى→ي, ة→ه
    - collapse long repeated characters (سلاااام → سلام)
    """
    if not s:
        return s
    s = s.replace(_TATWEEL, "")
    s = _AR_DIACRITICS_RE.sub("", s)
    s = (s
         .replace("أ", "ا")
         .replace("إ", "ا")
         .replace("آ", "ا")
         .replace("ى", "ي")
         .replace("ة", "ه"))
    s = re.sub(r"(.)\1{2,}", r"\1", s)
    return s

def dearabizi(s: str) -> str:
    """
    Replace common Arabizi numerals with Arabic letters.
    Example: rd 3alay → رد علي
    """
    if not s:
        return s
    return s.translate(_ARABIZI_MAP)

def parse_local_day(text: str | None, tz_name: str) -> date:
    """
    Accepts: 'today', 'yesterday', 'YYYY-MM-DD', or None (→ today).
    Uses the given tz to resolve 'today'.
    """
    z = ZoneInfo(tz_name)
    now_local = datetime.now(z)
    if not text or not str(text).strip():
        return now_local.date()
    t = str(text).strip().lower()
    if t in {"today", "الْيَوْم", "اليوم"}:
        return now_local.date()
    if t in {"yesterday", "امس", "أمس"}:
        return (now_local - timedelta(days=1)).date()
    # try ISO date
    try:
        y, m, d = map(int, t.split("-"))
        return date(y, m, d)
    except Exception:
        return now_local.date()

def local_day_bounds_utc(d: date, tz_name: str) -> tuple[datetime, datetime]:
    """
    Returns (start_utc, end_utc) for the local calendar day in tz_name.
    """
    z = ZoneInfo(tz_name)
    start_local = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=z)
    end_local   = start_local + timedelta(days=1)
    return (start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc))

def short(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n-1] + "…"

def chunk_by_len(s: str, maxlen: int):
    """Yield string chunks at most maxlen long."""
    i = 0
    while i < len(s):
        yield s[i:i+maxlen]
        i += maxlen

def _safe_zoneinfo(tz_name: str):
    candidates = [tz_name, "Asia/Gaza", "Asia/Jerusalem", "Asia/Amman", "UTC"]
    for cand in candidates:
        try:
            return ZoneInfo(cand)
        except Exception:
            continue
    return timezone.utc

def parse_local_day(text: str | None, tz_name: str) -> date:
    z = _safe_zoneinfo(tz_name)
    now_local = datetime.now(z)
    if not text or not str(text).strip():
        return now_local.date()
    t = str(text).strip().lower()
    if t in {"today", "الْيَوْم", "اليوم"}:
        return now_local.date()
    if t in {"yesterday", "امس", "أمس"}:
        return (now_local - timedelta(days=1)).date()
    try:
        y, m, d = map(int, t.split("-"))
        return date(y, m, d)
    except Exception:
        return now_local.date()

def local_day_bounds_utc(d: date, tz_name: str) -> tuple[datetime, datetime]:
    z = _safe_zoneinfo(tz_name)
    start_local = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=z)
    end_local   = start_local + timedelta(days=1)
    return (start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc))

def format_local_hm(dt_utc: datetime, tz_name: str) -> str:
    """Return HH:MM local time string for a UTC datetime."""
    z = _safe_zoneinfo(tz_name)
    try:
        return dt_utc.astimezone(z).strftime("%H:%M")
    except Exception:
        return dt_utc.strftime("%H:%M")

def short(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n-1] + "…"

def chunk_by_len(s: str, maxlen: int):
    i = 0
    while i < len(s):
        yield s[i:i+maxlen]
        i += maxlen
