"""The one place that calls Claude. Returns None without ANTHROPIC_API_KEY or on any failure, so callers fall back."""

import json
import os
import sys

import httpx

MODEL = "claude-sonnet-5-5"
URL = "https://api.anthropic.com/v1/messages"


def ask_claude(system: str, user: str, max_tokens: int = 400) -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        response = httpx.post(
            URL,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": MODEL, "max_tokens": max_tokens, "system": system,
                  "messages": [{"role": "user", "content": user}]},
            timeout=30,
        )
        response.raise_for_status()
        return "".join(b.get("text", "") for b in response.json()["content"] if b.get("type") == "text")
    except Exception as error:  # noqa: BLE001
        print(f"Claude call failed: {type(error).__name__}", file=sys.stderr)
        return None


def ask_json(system: str, user: str, max_tokens: int = 400) -> dict | None:
    """ask_claude, parsed as one JSON object (the first {...} in the answer)."""
    text = ask_claude(system, user, max_tokens)
    if not text or "{" not in text:
        return None
    try:
        found = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except ValueError:
        return None
    return found if isinstance(found, dict) else None
