"""Analyzes probe responses and network evidence to produce a verdict.

Scoring model:
  - Censorship pairs: compare each sensitive prompt's answer against its
    structurally equivalent control prompt's answer. Deflection/refusal/omission
    on the sensitive side only is the classic PRC-model pattern.
  - Self-ID: regex the replies for provider names and known model strings.
  - Reasoning leak: literal <think>...</think> tags indicate DeepSeek-R1-family.
  - Network: domains/headers observed from fingerprints/models.json.

Each model key accumulates weighted points; the highest total wins. Confidence
depends on how many independent signal categories agree.
"""
import re
from typing import Optional

from detector.fingerprint_db import display_name
from detector.probes import CENSORSHIP_PAIRS, SELF_ID_PROBES

# Model families. Censorship hits identify the PRC family, not one exact model.
PRC_FAMILY = {"deepseek", "qwen", "glm_zhipu", "moonshot_kimi", "ernie_baidu"}
WESTERN_FAMILY = {"openai_gpt", "anthropic_claude", "google_gemini", "mistral_ai", "meta_llama"}

WEIGHT_NETWORK_DOMAIN = 3.0
WEIGHT_NETWORK_HEADER = 2.0
WEIGHT_REASONING_LEAK = 2.5
WEIGHT_SELF_ID_MENTION = 1.0
WEIGHT_CENSORSHIP_FAMILY_HIT = 0.5

MIN_SUBSTANTIVE_CHARS = 80

_REFUSAL_PATTERNS = [
    r"i (?:can'?t|cannot|am unable|'m unable|am not able|'m not able)",
    r"i (?:apolog\w+|'m sorry| am sorry)",
    r"(?:against|violat\w+) (?:my|our) (?:guidelines|policies|rules|programming)",
    r"i (?:won'?t|will not) (?:help|provide|discuss|answer|engage)",
    r"not (?:something i can|able to) (?:help|assist|provide|discuss)",
    r"i (?:don'?t|do not) (?:feel comfortable|have (?:any )?information)",
    r"let'?s (?:talk about|discuss|focus on) something else",
    r"i'?d rather not",
    r"it'?s (?:not appropriate|inappropriate) (?:for me )?to (?:comment|discuss|provide)",
    r"i (?:can'?t|cannot) (?:comment|discuss|assist|provide) (?:with|on) (?:this|that)",
]

_PRC_DEFLECTION_PATTERNS = [
    r"(?:this|that|it) (?:is|'s) (?:a |very )?(?:sensitive|complex|controversial) (?:topic|subject|question|issue)",
    r"(?:need|needs|should) (?:to )?(?:be )?(?:more )?objective",
    r"(?:objective|comprehensive|rational|balanced|neutral|calm) (?:and|or|,| manner| way| perspective)",
    r"(?:harmonious|harmony|stable) (?:society|development|environment)",
    r"(?:in accordance with|based on|comply with) (?:chinese )?(?:law|laws|regulation|regulations)",
    r"(?:please |let'?s )(?:focus|talk) on (?:the )?(?:more )?positive",
    r"maintain (?:social )?(?:stability|harmony)",
]

_SELF_ID_PATTERNS = {
    "openai_gpt": [r"\bgpt-?\d", r"\bchatgpt\b", r"\bopenai\b"],
    "anthropic_claude": [r"\bclaude\b", r"\banthropic\b"],
    "google_gemini": [r"\bgemini\b", r"\bbard\b", r"\bdeepmind\b"],
    "mistral_ai": [r"\bmistral\b", r"\bmixtral\b"],
    "meta_llama": [r"\bllama\s?\d", r"\bmeta\s?ai\b"],
    "deepseek": [r"\bdeepseek\b"],
    "qwen": [r"\bqwen\b", r"\btongyi\b", r"\balibaba\b"],
    "glm_zhipu": [r"\bchatglm\b", r"\bglm-?\d", r"\bzhipu\b"],
    "moonshot_kimi": [r"\bkimi\b", r"\bmoonshot\b"],
    "ernie_baidu": [r"\bernie\b", r"\bwenxin\b", r"\bbaidu\b"],
}


def _excerpt(text: str, limit: int = 180) -> str:
    t = " ".join((text or "").split())
    if len(t) <= limit:
        return t
    return t[:limit] + "..."


def _matches_any(text: str, patterns: list) -> bool:
    low = text.lower()
    return any(re.search(p, low) for p in patterns)


def classify_answer(text: str) -> str:
    """Classify a probe answer as 'substantive', 'deflected', or 'empty'."""
    t = (text or "").strip()
    if len(t) < 10:
        return "empty"
    if _matches_any(t, _REFUSAL_PATTERNS):
        return "deflected"
    if _matches_any(t, _PRC_DEFLECTION_PATTERNS):
        return "deflected"
    if len(t) < MIN_SUBSTANTIVE_CHARS:
        return "deflected"
    return "substantive"


def _analyze_censorship(responses: dict) -> dict:
    pairs = []
    hits = 0
    for label, _sens, _ctrl in CENSORSHIP_PAIRS:
        s_text = responses.get(label + "__sensitive", "")
        c_text = responses.get(label + "__control", "")
        s_status = classify_answer(s_text)
        c_status = classify_answer(c_text)
        hit = s_status in ("deflected", "empty") and c_status == "substantive"
        if hit:
            hits += 1
        pairs.append({
            "label": label,
            "sensitive_status": s_status,
            "control_status": c_status,
            "hit": hit,
            "sensitive_excerpt": _excerpt(s_text),
            "control_excerpt": _excerpt(c_text),
        })
    total = len(CENSORSHIP_PAIRS)
    ratio = round(hits / total, 2) if total else 0.0
    return {"pairs": pairs, "hits": hits, "total": total, "ratio": ratio}


def _analyze_self_id(responses: dict) -> dict:
    matches = {}  # model_key -> [evidence strings]
    for label, _prompt in SELF_ID_PROBES:
        text = responses.get(label, "") or ""
        for model_key, patterns in _SELF_ID_PATTERNS.items():
            for pat in patterns:
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    snippet = _excerpt(text, 120)
                    evidence = label + ": '" + m.group(0) + "' in \"" + snippet + "\""
                    matches.setdefault(model_key, []).append(evidence)
                    break
    return {"matches": matches}


def _analyze_reasoning_leak(responses: dict) -> dict:
    for label, text in responses.items():
        m = re.search(r"<think>.*?</think>", text or "", re.DOTALL | re.IGNORECASE)
        if m:
            return {"found": True, "probe": label, "snippet": _excerpt(m.group(0), 300)}
    for label, text in responses.items():
        if re.search(r"<think>", text or "", re.IGNORECASE):
            return {"found": True, "probe": label, "snippet": _excerpt(text, 300)}
    return {"found": False, "probe": None, "snippet": ""}


def analyze(responses: dict, network_summary: dict, db: dict,
            claimed_key: Optional[str] = None) -> dict:
    """Produce the full analysis from raw probe responses + network evidence."""
    censorship = _analyze_censorship(responses)
    self_id = _analyze_self_id(responses)
    leak = _analyze_reasoning_leak(responses)

    scores = {key: 0.0 for key in db}

    # Network evidence (strongest signal).
    for key, ev in (network_summary or {}).items():
        if key in scores:
            scores[key] += WEIGHT_NETWORK_DOMAIN * ev.get("requests", 0)
            scores[key] += WEIGHT_NETWORK_HEADER * sum(ev.get("headers", {}).values())

    # Reasoning-tag leak points at DeepSeek-R1-family.
    if leak["found"] and "deepseek" in scores:
        scores["deepseek"] += WEIGHT_REASONING_LEAK

    # Self-ID mentions (capped so one rambling answer cannot dominate).
    for key in self_id["matches"]:
        if key in scores:
            scores[key] += WEIGHT_SELF_ID_MENTION * min(len(self_id["matches"][key]), 3)

    # Censorship pattern points at the PRC family, not one exact model.
    if censorship["hits"]:
        for key in PRC_FAMILY:
            if key in scores:
                scores[key] += WEIGHT_CENSORSHIP_FAMILY_HIT * censorship["hits"]

    top_key = max(scores, key=scores.get) if scores else None
    top_score = scores.get(top_key, 0.0) if top_key else 0.0

    signals = []
    ev = (network_summary or {}).get(top_key) if top_key else None
    if ev and (ev.get("requests") or ev.get("headers")):
        signals.append("network")
    if top_key in self_id["matches"]:
        signals.append("self_id")
    if censorship["hits"] and top_key in PRC_FAMILY:
        signals.append("censorship")
    if leak["found"] and top_key == "deepseek":
        signals.append("reasoning_leak")

    if top_score <= 0 or not top_key:
        confidence = "none"
    elif len(signals) >= 2:
        confidence = "high"
    elif len(signals) == 1:
        confidence = "medium" if top_score >= WEIGHT_NETWORK_DOMAIN else "low"
    else:
        confidence = "low"

    verdict = {
        "model_key": top_key if top_score > 0 else None,
        "display_name": display_name(top_key, db) if top_score > 0 else "unknown",
        "confidence": confidence,
        "score": round(top_score, 2),
        "supporting_signals": signals,
    }

    claimed = None
    if claimed_key:
        same_family = False
        if top_score > 0 and top_key:
            both_prc = claimed_key in PRC_FAMILY and top_key in PRC_FAMILY
            both_western = claimed_key in WESTERN_FAMILY and top_key in WESTERN_FAMILY
            same_family = both_prc or both_western
        claimed = {
            "key": claimed_key,
            "display_name": display_name(claimed_key, db),
            "matches_verdict": bool(top_score > 0 and claimed_key == top_key),
            "same_family": bool(same_family),
        }

    return {
        "verdict": verdict,
        "scores": dict(sorted(scores.items(), key=lambda kv: kv[1], reverse=True)),
        "censorship": censorship,
        "self_id": self_id,
        "reasoning_leak": leak,
        "network": network_summary or {},
        "claimed": claimed,
        "responses": responses,
    }
