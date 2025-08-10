"""
core/analyzer.py
----------------
Weekly analytics, charts, and team summaries for MindPulse.

Responsibilities:
- Persist and read mood logs (UTF-8 JSON).
- Append per-message sentiment logs.
- Build weekly reports:
  * Mood distribution + trend vs previous week
  * "Stress window" (weekday/hour with most negatives)
  * Focused reflections with AI tips (top-k pain points)
  * Optional pie chart (headless Matplotlib)
- Build a manager’s team summary (% of dominant mood in last 7 days).
"""

from __future__ import annotations
import os, json
from datetime import datetime, timedelta
from collections import Counter
from typing import List, Tuple, Optional

from core.feedback import suggest_better_response
from core.utils import CHARTS_DIR as DEFAULT_CHARTS_DIR

MOOD_LOG_FILE = os.getenv("MOOD_LOG_FILE", "data/mood_logs.json")
CHARTS_DIR    = os.getenv("CHARTS_DIR", str(DEFAULT_CHARTS_DIR))
NEG_CUTOFF    = float(os.getenv("ANALYZER_NEG_CUTOFF", "-0.40"))
MAX_REFLECTIONS = int(os.getenv("ANALYZER_MAX_REFLECTIONS", "5"))
MIN_SAMPLES     = int(os.getenv("ANALYZER_MIN_SAMPLES", "1"))

# ------------------ IO helpers (UTF-8) ------------------

def load_logs() -> List[dict]:
    if not os.path.exists(MOOD_LOG_FILE):
        return []
    try:
        with open(MOOD_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Failed to read {MOOD_LOG_FILE}: {e}")
        return []

def save_logs(logs: List[dict]) -> None:
    try:
        os.makedirs(os.path.dirname(MOOD_LOG_FILE), exist_ok=True)
        with open(MOOD_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"❌ Failed to write {MOOD_LOG_FILE}: {e}")

# ------------------ Logging API ------------------

def log_mood(user_id: str, text: str, sentiment_result: dict) -> None:
    logs = load_logs()
    logs.append({
        "user_id": user_id,
        "timestamp": datetime.utcnow().isoformat(),
        "content": text,
        "sentiment": sentiment_result.get("label"),
        "score": float(sentiment_result.get("score", 0.0)),
    })
    save_logs(logs)

# ------------------ Time slicing helpers ------------------

def _week_range(days_back: int = 0) -> Tuple[datetime, datetime]:
    end = datetime.utcnow() - timedelta(days=days_back)
    start = end - timedelta(days=7)
    return start, end

def _slice_logs(start: datetime, end: datetime, user_id: Optional[str] = None) -> List[dict]:
    out: List[dict] = []
    for e in load_logs():
        if user_id and e.get("user_id") != user_id:
            continue
        ts = e.get("timestamp")
        if not ts:
            continue
        try:
            t = datetime.fromisoformat(ts)
        except Exception:
            continue
        if start <= t <= end:
            out.append(e)
    return out

def get_weekly_logs(user_id: str) -> List[dict]:
    start, end = _week_range(0)
    return _slice_logs(start, end, user_id=user_id)

# ------------------ Chart helper (headless) ------------------

def _create_mood_chart(mood_counts: Counter, user_id: str) -> Optional[str]:
    if not mood_counts:
        return None

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import uuid
    except Exception:
        return None

    labels = list(mood_counts.keys())
    sizes  = list(mood_counts.values())
    colors = {"positive": "#66bb6a", "neutral": "#ffee58", "negative": "#ef5350"}

    os.makedirs(CHARTS_DIR, exist_ok=True)
    fig, ax = plt.subplots()
    ax.pie(
        sizes,
        labels=[lbl.capitalize() for lbl in labels],
        autopct="%1.1f%%",
        startangle=90,
        colors=[colors.get(lbl, "#90caf9") for lbl in labels],
    )
    ax.axis("equal")
    plt.title("Your Mood This Week")

    filename = f"chart_{user_id}_{uuid.uuid4().hex[:6]}.png"
    path = os.path.join(CHARTS_DIR, filename)
    plt.savefig(path, bbox_inches="tight")
    plt.close()
    return path

# ------------------ Analytics helpers ------------------

def _most_stress_window(logs: List[dict]) -> Optional[str]:
    buckets = Counter()
    for e in logs:
        try:
            score = float(e.get("score", 0))
            is_neg = (e.get("sentiment") == "negative") or (score < NEG_CUTOFF)
            if not is_neg:
                continue
            t = datetime.fromisoformat(e["timestamp"])
            buckets[(t.weekday(), t.hour)] += 1
        except Exception:
            continue

    if not buckets:
        return None
    (wd, hr), _ = buckets.most_common(1)[0]
    weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][wd]
    return f"{weekday} around {hr:02d}:00"

def _award_badges(logs: List[dict]) -> List[str]:
    pos = sum(1 for e in logs if e.get("sentiment") == "positive")
    neg = sum(1 for e in logs if (e.get("sentiment") == "negative") or (float(e.get("score", 0)) < NEG_CUTOFF))
    days = {datetime.fromisoformat(e["timestamp"]).date() for e in logs if e.get("timestamp")}
    badges: List[str] = []
    if pos >= 5:
        badges.append("🌟 Uplifter (shared 5+ positive moments)")
    if neg <= 1:
        badges.append("🛡 Calm Communicator (kept cool under pressure)")
    if len(days) >= 5:
        badges.append("📅 Consistent (active 5+ days)")
    return badges

# ------------------ Weekly report ------------------

def generate_weekly_report(user_id: str) -> tuple[str, Optional[str]]:
    # This week vs last week
    start_w, end_w = _week_range(0)
    start_prev, end_prev = _week_range(7)

    logs = _slice_logs(start_w, end_w, user_id=user_id)
    prev = _slice_logs(start_prev, end_prev, user_id=user_id)

    if len(logs) < MIN_SAMPLES:
        return "No messages logged for you in the past 7 days.", None

    # Distribution
    mood_counts = Counter(e.get("sentiment") for e in logs if e.get("sentiment"))
    total = sum(mood_counts.values()) or 1

    mood_summary = "\n".join(
        f"- {label.capitalize()}: {count} ({int(count/total*100)}%)"
        for label, count in mood_counts.items()
    )

    # Trend vs last week
    def _pos_ratio(arr: List[dict]) -> float:
        c = Counter(e.get("sentiment") for e in arr if e.get("sentiment"))
        t = sum(c.values()) or 1
        return (c.get("positive", 0) / t) if t else 0.0

    trend_arrow = "➡️ flat"
    try:
        pr_now = _pos_ratio(logs)
        pr_prev = _pos_ratio(prev)
        if pr_now > pr_prev: trend_arrow = "📈 up"
        elif pr_now < pr_prev: trend_arrow = "📉 down"
    except Exception:
        pass

    # High-signal pain points
    pain_points = sorted(
        (
            e for e in logs
            if (e.get("sentiment") == "negative") or (float(e.get("score", 0)) < NEG_CUTOFF)
        ),
        key=lambda x: float(x.get("score", 0))
    )[:MAX_REFLECTIONS]

    reflections: List[str] = []
    for e in pain_points:
        tip = suggest_better_response(e.get("content", ""))
        try:
            ts = datetime.fromisoformat(e.get("timestamp", "")).strftime("%A %H:%M")
        except Exception:
            ts = "Unknown time"
        reflections.append(
            f"🕒 **{ts}**\n"
            f"💬 *\"{e.get('content','')}\"*\n"
            f"💡 {tip}"
        )

    stress_hint = _most_stress_window(logs)
    badges = _award_badges(logs)
    chart_path = _create_mood_chart(mood_counts, user_id)

    parts: List[str] = []
    parts.append("🧘 **Your Weekly Mood Report**")
    parts.append(f"**Mood Distribution:**\n{mood_summary}")
    parts.append(f"**Trend vs last week:** {trend_arrow}")
    if stress_hint:
        parts.append(f"**Stress seemed highest:** {stress_hint}")
    if badges:
        parts.append("**New badges unlocked:** " + "  ".join(badges))
    parts.append("**Situations to Reflect On:**\n" + ("\n\n".join(reflections) if reflections else "✅ No major concerns this week — great balance!"))

    return "\n\n".join(parts), chart_path

# ------------------ Manager team summary ------------------

def get_team_summary(manager_id: str) -> str:
    try:
        from commands.assign import get_users_for_manager
    except Exception as e:
        print("Import error in get_team_summary:", e)
        return "❌ Unable to load team configuration."

    users = set(get_users_for_manager(manager_id))
    if not users:
        return "👥 You don't manage anyone yet."

    logs = load_logs()
    cutoff = datetime.utcnow() - timedelta(days=7)
    relevant: List[dict] = []
    for e in logs:
        if e.get("user_id") not in users:
            continue
        ts = e.get("timestamp")
        if not ts:
            continue
        try:
            if datetime.fromisoformat(ts) >= cutoff:
                relevant.append(e)
        except Exception:
            continue

    if not relevant:
        return "📉 No mood data from your team this week."

    counts = Counter(e.get("sentiment") for e in relevant if e.get("sentiment"))
    total = sum(counts.values()) or 1
    label, count = counts.most_common(1)[0]
    pct = int(count / total * 100)
    return f"📊 Your team's overall feel is: **{pct}% {label.capitalize()}**"
