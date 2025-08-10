"""
core/config.py
--------------
Single source of truth for runtime configuration.
Reads environment variables, exposes a frozen `cfg` object.

Usage:
    from core.config import cfg
    if cfg.harm_debug: ...
"""



from __future__ import annotations
from dataclasses import dataclass
import os

@dataclass(frozen=True)
class Config:
    # Azure OpenAI
    azure_key: str
    azure_endpoint: str
    azure_deployment: str
    azure_api_version: str

    # Sentiment engine
    sentiment_engine: str
    sentiment_pos_thresh: float
    sentiment_neg_thresh: float

    # Harm detection general
    harm_detector: str         # "azure" | "heuristic" | "hybrid"
    harm_severity_min: str     # "low" | "medium" | "high"
    harm_debug: bool

def _bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in {"1","true","yes","y","on"}

def _float(v: str | None, default: float) -> float:
    try:
        return float(v) if v is not None else default
    except Exception:
        return default

def _str(v: str | None, default: str) -> str:
    return v if v else default

cfg = Config(
    azure_key         = _str(os.getenv("AZURE_OPENAI_KEY"), ""),
    azure_endpoint    = _str(os.getenv("AZURE_OPENAI_ENDPOINT"), "").rstrip("/"),
    azure_deployment  = _str(os.getenv("AZURE_OPENAI_DEPLOYMENT"), "gpt-4.1"),
    azure_api_version = _str(os.getenv("AZURE_OPENAI_API_VERSION"), "2025-01-01-preview"),

    sentiment_engine      = _str(os.getenv("SENTIMENT_ENGINE"), "hybrid"),
    sentiment_pos_thresh  = _float(os.getenv("SENTIMENT_POS_THRESH"), 0.30),
    sentiment_neg_thresh  = _float(os.getenv("SENTIMENT_NEG_THRESH"), -0.30),

    harm_detector     = _str(os.getenv("HARM_DETECTOR"), "hybrid").lower(),
    harm_severity_min = _str(os.getenv("HARM_SEVERITY_MIN"), "medium").lower(),
    harm_debug        = _bool(os.getenv("HARM_DEBUG"), False),
)
