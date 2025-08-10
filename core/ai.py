"""
core/ai.py
----------
Central AI gateway for MindPulse.

Responsibilities:
- Provide a *single* interface for AI operations used by the app:
  * sentiment(text, context_lines)
  * classify_harm(text, context_lines)
  * coaching_tip(text, lang_code)
  * weekly_tip(text, lang_code)
- Route to Azure OpenAI (chat completions) using environment config.
- Offer safe fallbacks (VADER for sentiment; heuristics for harm) when needed.
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional
import json
import requests

from core.config import cfg

# -------- Low-level Azure Chat Completions --------

def _azure_chat(messages: List[Dict[str, str]], temperature: float = 0.6, max_tokens: int = 300) -> str:
    """
    Synchronous call to Azure OpenAI Chat Completions.
    We keep it sync because the caller uses asyncio.to_thread() around us.
    """
    if not cfg.azure_key or not cfg.azure_endpoint or not cfg.azure_deployment:
        raise RuntimeError("Azure OpenAI not configured. Check .env.")

    url = (
        f"{cfg.azure_endpoint}/openai/deployments/"
        f"{cfg.azure_deployment}/chat/completions"
        f"?api-version={cfg.azure_api_version}"
    )

    payload = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Content-Type": "application/json",
        "api-key": cfg.azure_key,
    }

    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    # Standard Chat Completions shape
    return data["choices"][0]["message"]["content"]

# -------- Utilities --------

def _safe_json_extract(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1 and e > s:
            try:
                return json.loads(text[s:e+1])
            except Exception:
                return {}
        return {}

# -------- Public API --------

class _AI:
    """
    Facade exposing the AI features. Do not call _azure_chat directly elsewhere.
    """

    def sentiment(self, text: str, context_lines: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Multilingual, context-aware sentiment with fallback to VADER thresholds.
        Returns: {"label": "positive|neutral|negative", "score": float}
        """
        # Try Azure first (if configured)
        try:
            ctx = "\n".join(context_lines or [])
            # inside _AI.classify_harm (core/ai.py), just before calling _azure_chat(...)
            prompt = (
                "You are a multilingual moderation classifier. "
                "Determine if the message is aggressive/harassing/toxic in its own language. "
                "If it insults a person, treat as harmful. "
                "Return ONLY JSON with keys: is_harmful (boolean), severity (low|medium|high), language (ISO), reason (short).\n\n"
                "Examples:\n"
                "- Input: 'ولك انقلع من هون' → {\"is_harmful\": true, \"severity\": \"medium\", \"language\": \"ar\", \"reason\": \"insult/command\"}\n"
                "- Input: 'hazem rd 3alay' → {\"is_harmful\": true, \"severity\": \"low\", \"language\": \"ar\", \"reason\": \"imperative/taunting\"}\n\n"
                f"Context (most recent first):\n{ctx}\n\n"
                f"Message:\n{text}"
            )
            out = _azure_chat(
                [
                    {"role": "system", "content": "Return strict JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=120,
            )
            data = _safe_json_extract(out)
            label = str(data.get("label", "neutral")).lower()
            score = float(data.get("score", 0))
            if label not in {"positive","neutral","negative"}:
                label = "neutral"
            return {"label": label, "score": score}
        except Exception:
            pass  # fall back

        # Fallback: VADER thresholds
        try:
            from nltk.sentiment import SentimentIntensityAnalyzer
            import nltk
            nltk.download('vader_lexicon', quiet=True)
            sia = SentimentIntensityAnalyzer()
            score = sia.polarity_scores(text)['compound']
            if score > cfg.sentiment_pos_thresh:
                label = "positive"
            elif score < cfg.sentiment_neg_thresh:
                label = "negative"
            else:
                label = "neutral"
            return {"label": label, "score": float(score)}
        except Exception:
            # ultimate fallback
            return {"label": "neutral", "score": 0.0}

    def classify_harm(self, text: str, context_lines: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Multilingual harassment/toxicity classifier.
        Returns: {"is_harmful": bool, "severity": "low|medium|high", "language": "xx", "reason": "..."}
        """
        try:
            ctx = "\n".join(context_lines or [])
            prompt = (
                "You are a multilingual moderation classifier. "
                "Determine if the message is aggressive/harassing/toxic in its own language. "
                "If it insults a person (e.g., calling them 'fat', 'stupid', etc.), treat as harmful. "
                "Return ONLY JSON with keys: is_harmful (boolean), severity (low|medium|high), language (ISO), reason (short).\n\n"
                f"Context (most recent first):\n{ctx}\n\n"
                f"Message:\n{text}"
            )
            out = _azure_chat(
                [
                    {"role": "system", "content": "Return strict JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=140,
            )
            data = _safe_json_extract(out)
            return {
                "is_harmful": bool(data.get("is_harmful", False)),
                "severity": str(data.get("severity", "low")).lower(),
                "language": str(data.get("language", "und")).lower(),
                "reason": str(data.get("reason", "")),
            }
        except Exception:
            # conservative fallback (not harmful)
            return {"is_harmful": False, "severity": "low", "language": "und", "reason": "fallback"}

    def coaching_tip(self, text: str, lang_code: Optional[str] = None) -> str:
        """
        Short 1–2 sentence empathetic suggestion to de-escalate and rephrase.
        Try to respond in the same language as the message if detectable.
        """
        try:
            prompt = (
                "The following workplace chat message seems emotionally aggressive. "
                "Respond with a SHORT (1–2 sentences) empathetic suggestion to calm down "
                "and rephrase constructively. Reply in the SAME language as the message. "
                "Avoid judging; be kind, practical.\n\n"
                f"Message:\n{text}"
            )
            out = _azure_chat(
                [
                    {"role": "system", "content": "You are a calm, multilingual workplace communication coach."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=120,
            )
            return out.strip()
        except Exception:
            # multilingual generic tip
            return ".خذ لحظة لتهدأ وأعد صياغة ردك بطريقة بنّاءة 💡" \
            "💡 A short pause can help; try rephrasing constructively."

    def weekly_tip(self, text: str, lang_code: Optional[str] = None) -> str:
        """
        For weekly reflection entries: give a kind, practical suggestion and
        a more professional alternative phrasing (2–3 sentences total).
        """
        try:
            prompt = (
                "A user wrote this in a workplace chat. It came across as tense/negative.\n"
                "Give supportive, actionable advice (1–2 sentences) AND suggest a more professional rephrase (1 sentence). "
                "Keep tone warm, specific, realistic. Use the SAME language as the message.\n\n"
                f"Message:\n{text}"
            )
            out = _azure_chat(
                [
                    {"role": "system", "content": "You are a friendly, culturally aware communication coach. Reply in strict plain text."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=180,
            )
            return out.strip()
        except Exception:
            return "Tip: pause, breathe, and describe the issue factually, then propose a next step. For example: “Could we revisit the deployment plan to avoid the outage?”"

    # at the end of class _AI
    def health_check(self) -> dict:
        try:
            out = _azure_chat(
                [
                    {"role": "system", "content": "Return the single word: ok"},
                    {"role": "user", "content": "Say: ok"},
                ],
                temperature=0.0,
                max_tokens=5,
            )
            ok = out.strip().lower().startswith("ok")
            return {"ok": bool(ok), "why": ("ok" if ok else f"unexpected reply: {out[:50]}")}
        except Exception as e:
            return {"ok": False, "why": f"{type(e).__name__}: {e}"}

# Singleton
ai = _AI()
