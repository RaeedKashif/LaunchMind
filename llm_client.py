"""Shared Groq LLM client (REST, no SDK) used by all agents.

Tier-based fallback:
    Tier 1: PRIMARY_MODEL + GROQ_API_KEY
    Tier 2: PRIMARY_MODEL + GROQ_API_KEY_2
    Tier 3: FALLBACK_MODEL + GROQ_API_KEY
    Tier 4: FALLBACK_MODEL + GROQ_API_KEY_2
    ... (extends automatically with GROQ_API_KEY_3, _4, ...)

On 429 / 401 / 403 / 413 the client advances to the next tier with no
sleep. Once all tiers are exhausted, it falls back to exponential backoff
on the last tier.
"""
import json
import os
import re
import time
import requests

PRIMARY_MODEL = "llama-3.3-70b-versatile"   # better, lower daily quota
FALLBACK_MODEL = "llama-3.1-8b-instant"     # weaker, higher daily quota
ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

_tier_index = 0
_tiers_cache = None


def _load_keys() -> list:
    keys = []
    primary = os.environ.get("GROQ_API_KEY")
    if primary:
        keys.append(primary)
    i = 2
    while True:
        k = os.environ.get(f"GROQ_API_KEY_{i}")
        if not k:
            break
        keys.append(k)
        i += 1
    if not keys:
        raise RuntimeError("No GROQ_API_KEY found in environment")
    return keys


def _tiers() -> list:
    """All (model, key) combinations, primary model first."""
    global _tiers_cache
    if _tiers_cache is None:
        keys = _load_keys()
        _tiers_cache = (
            [(PRIMARY_MODEL, k) for k in keys]
            + [(FALLBACK_MODEL, k) for k in keys]
        )
    return _tiers_cache


def _rotate_tier(reason: str) -> bool:
    global _tier_index
    tiers = _tiers()
    if _tier_index + 1 < len(tiers):
        _tier_index += 1
        model, _ = tiers[_tier_index]
        print(f"  [LLM] {reason} - advancing to tier {_tier_index + 1}/{len(tiers)} (model={model})")
        return True
    return False


def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
    backoffs = [10, 25, 60]
    last_err = None

    for attempt, wait in enumerate([0] + backoffs):
        if wait:
            print(f"  [LLM] sleeping {wait}s before retry (attempt {attempt + 1})")
            time.sleep(wait)

        tiers = _tiers()
        model, key = tiers[_tier_index]
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        try:
            r = requests.post(ENDPOINT, headers=headers, json=body, timeout=60)

            if r.status_code == 429:
                retry_after = int(r.headers.get("retry-after", 0)) or None
                print(f"  [LLM] 429 rate limited on tier {_tier_index + 1} (retry-after={retry_after}s)")
                if _rotate_tier("429"):
                    continue
                if retry_after:
                    time.sleep(min(retry_after, 60))
                last_err = f"429: {r.text[:200]}"
                continue

            if r.status_code in (401, 403):
                print(f"  [LLM] auth error {r.status_code} on tier {_tier_index + 1}")
                if _rotate_tier(f"auth {r.status_code}"):
                    continue
                last_err = f"{r.status_code}: {r.text[:200]}"
                continue

            if r.status_code == 413:
                # Payload too large - usually only an issue on 8b. Drop to next tier.
                print(f"  [LLM] 413 payload too large on tier {_tier_index + 1}")
                if _rotate_tier("413"):
                    continue
                last_err = "413 payload too large, no more tiers"
                continue

            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

        except requests.RequestException as e:
            last_err = str(e)
            print(f"  [LLM] request error on tier {_tier_index + 1}: {e}")

    raise RuntimeError(f"LLM call failed after retries: {last_err}")


def _loose_loads(s):
    """json.loads with strict=False so unescaped control chars don't fail."""
    return json.loads(s, strict=False)


def parse_llm_json(text: str) -> dict:
    """Extract JSON from an LLM response, tolerating markdown fences."""
    try:
        return _loose_loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            return _loose_loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        return _loose_loads(match.group(0))
    raise ValueError(f"Could not parse JSON from LLM response: {text[:200]}")
