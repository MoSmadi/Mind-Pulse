"""
core/feedback.py
----------------
Generates supportive suggestions for weekly reports (language-aware).
This file keeps a clean interface for analyzer.py without exposing prompt logic.
"""

from __future__ import annotations
from core.ai import ai

def suggest_better_response(text: str, lang_code: str | None = None) -> str:
    """
    Return a short, kind, practical suggestion and a more professional phrasing.
    Language is enforced by ai.weekly_tip() (respects env preferences).
    """
    return ai.weekly_tip(text, lang_code)
