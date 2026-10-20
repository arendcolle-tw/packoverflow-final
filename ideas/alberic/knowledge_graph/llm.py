"""The one place that calls a language model. Claude with ANTHROPIC_API_KEY, else Gemini on Vertex AI with the Cloud Run
service's own identity (no key). Returns None on any failure, so callers fall back to templates."""

import json
import os
import sys

import httpx

MODEL = "claude-sonnet-5-5"
URL = "https://api.anthropic.com/v1/messages"
GEMINI = os.environ.get("KG_GEMINI_MODEL", "gemini-2.5-flash")
REGION = "us-central1"
METADATA = "http://metadata.google.internal/computeMetadata/v1"


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


def ask_gemini(system: str, user: str, max_tokens: int = 400) -> str | None:
    """Vertex AI generateContent, authorised by the metadata server's token. Only on Cloud Run (K_SERVICE)."""
    if "K_SERVICE" not in os.environ:
        return None
    try:
        flavor = {"Metadata-Flavor": "Google"}
        token = httpx.get(f"{METADATA}/instance/service-accounts/default/token", headers=flavor, timeout=5).json()["access_token"]
        project = httpx.get(f"{METADATA}/project/project-id", headers=flavor, timeout=5).text
        response = httpx.post(
            f"https://{REGION}-aiplatform.googleapis.com/v1/projects/{project}/locations/{REGION}/publishers/google/models/{GEMINI}:generateContent",
            headers={"Authorization": f"Bearer {token}"}, timeout=30,
            json={"systemInstruction": {"parts": [{"text": system}]},
                  "contents": [{"role": "user", "parts": [{"text": user}]}],
                  "generationConfig": {"maxOutputTokens": max_tokens + 600, "temperature": 0.2,
                                       "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}},
        )
        response.raise_for_status()
        parts = response.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except Exception as error:  # noqa: BLE001
        print(f"Gemini call failed: {type(error).__name__}", file=sys.stderr)
        return None


def ask_json(system: str, user: str, max_tokens: int = 400) -> dict | None:
    """The first {...} in the model's answer, with `_by` naming the model ("claude" or "gemini")."""
    for by, ask in (("claude", ask_claude), ("gemini", ask_gemini)):
        text = ask(system, user, max_tokens)
        if not text or "{" not in text:
            continue
        try:
            found = json.loads(text[text.index("{"): text.rindex("}") + 1])
        except ValueError:
            continue
        if isinstance(found, dict):
            return {**found, "_by": by}
    return None
