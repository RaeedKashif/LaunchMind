"""Shared Groq LLM client used by all agents (free tier)."""
import json
import os
import re
from groq import Groq

_client = None
MODEL = "llama-3.3-70b-versatile"


def _get_client():
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
    response = _get_client().chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content


def parse_llm_json(text: str) -> dict:
    """Extract JSON from an LLM response, tolerating markdown fences."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        return json.loads(match.group(0))
    raise ValueError(f"Could not parse JSON from LLM response: {text[:200]}")
