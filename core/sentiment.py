"""
core/sentiment.py
-----------------
Thin convenience wrapper around the centralized AI service for sentiment.
Other modules should import `analyze_sentiment` from here (not call AI directly).
"""

from __future__ import annotations
from typing import List, Optional, Dict, Any
from core.ai import ai

def analyze_sentiment(text: str, context_lines: Optional[List[str]] = None) -> Dict[str, Any]:
    """Context-aware, multilingual sentiment with safe fallback."""
    return ai.sentiment(text, context_lines=context_lines)
