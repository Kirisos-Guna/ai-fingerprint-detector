"""Loads the known-model fingerprint database and resolves user-supplied
'--claims' strings (e.g. 'gpt-4', 'chatgpt', 'claude') to canonical model keys.
"""
import json

from detector import paths

FINGERPRINT_PATH = paths.fingerprints_dir() / "models.json"

CLAIM_ALIASES = {
    "gpt-4": "openai_gpt", "gpt4": "openai_gpt", "gpt-4o": "openai_gpt",
    "gpt-3.5": "openai_gpt", "gpt3.5": "openai_gpt", "chatgpt": "openai_gpt",
    "gpt": "openai_gpt", "openai": "openai_gpt",
    "claude": "anthropic_claude", "anthropic": "anthropic_claude",
    "gemini": "google_gemini", "bard": "google_gemini", "google": "google_gemini",
    "mistral": "mistral_ai",
    "llama": "meta_llama", "meta": "meta_llama",
    "deepseek": "deepseek",
    "qwen": "qwen", "alibaba": "qwen",
    "glm": "glm_zhipu", "chatglm": "glm_zhipu", "zhipu": "glm_zhipu",
    "kimi": "moonshot_kimi", "moonshot": "moonshot_kimi",
    "ernie": "ernie_baidu", "wenxin": "ernie_baidu", "baidu": "ernie_baidu",
}


def load_db() -> dict:
    with open(FINGERPRINT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_claim(claim: str, db: dict):
    """Map a free-text --claims value to a canonical fingerprint DB key, or None."""
    if not claim:
        return None
    key = claim.strip().lower()
    if key in db:
        return key
    if key in CLAIM_ALIASES:
        return CLAIM_ALIASES[key]
    for alias, target in CLAIM_ALIASES.items():
        if alias in key:
            return target
    return None


def display_name(key: str, db: dict) -> str:
    if not key:
        return "unknown"
    return db.get(key, {}).get("display_name", key)


def all_domain_index(db: dict) -> dict:
    """Build a domain-substring -> model_key lookup for quick matching."""
    index = {}
    for key, entry in db.items():
        for domain in entry.get("network", {}).get("domains", []):
            index[domain.lower()] = key
    return index


def all_header_index(db: dict) -> dict:
    """Build a header-name -> [model_key, ...] lookup."""
    index = {}
    for key, entry in db.items():
        for header in entry.get("network", {}).get("headers", []):
            index.setdefault(header.lower(), []).append(key)
    return index
