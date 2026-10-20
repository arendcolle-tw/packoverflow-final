"""Knowly's answering agent: `claude -p` with the fact store tools, falling back to StoreClient.search on any failure."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from knowly.client import StoreClient
from knowly.config import person_key

TOOLS = ["mcp__knowly__search_facts", "mcp__knowly__person_facts", "mcp__knowly__recent_facts"]
SOURCE_KEYS = ("person", "task", "at", "why")
SCHEMA = {
    "type": "object",
    "properties": {
        "answered": {"type": "boolean"},
        "answer": {"type": "string"},
        "sources": {"type": "array", "maxItems": 5, "items": {
            "type": "object", "properties": {k: {"type": "string"} for k in SOURCE_KEYS}, "required": list(SOURCE_KEYS)}},
        "ask_person": {"type": ["string", "null"]},
        "why_them": {"type": ["string", "null"]},
        "ping": {"type": ["string", "null"]},
    },
    "required": ["answered", "answer", "sources", "ask_person", "why_them", "ping"],
}
# {person} stays a placeholder: Slack swaps in the <@U...> mention, MCP and /api/ask the plain name.
PING = "{person}, {asker} is asking: “{question}” Do you know?"
NO_ANSWER = "Based on what's in Knowly there's no answer to this yet"
SYSTEM = f"""You are Knowly, a team's fact-based knowledge base. Colleagues ask you questions in Slack or from their editor.

Always search the knowledge base before answering. Call search_facts with the question, then with shorter keyword queries (the system, the setting, synonyms). Use person_facts or recent_facts when that helps. Every fact has a person, their reason in their own words (why), the task it came from, the source (a Claude session, or a question answered in Slack) and a date.

Answer only from facts you found. Never use outside knowledge and never guess.

Write like a colleague replying in chat: plain, natural sentences, first names capitalised. No labels such as "Task:", "Reason:" or "Source:", no markdown, no headings, no lists, no dates unless the date matters to the answer.

When the facts answer the question: answered=true. answer is one or two sentences that give the answer, who decided it and why, for example: "The export starts at 16:00. Tristan chose that so three retries still finish before the bank closes the SFTP window at 18:00." sources lists the facts you used, each with person, task, at as YYYY-MM-DD, and why copied verbatim. ask_person, why_them and ping are null.

When the facts do not answer the question: answered=false. ask_person is the exact person value of whoever's facts are closest to the question, never the asker unless nobody else has related facts. answer says there is no answer yet and why that person is the one to ask, for example: "{NO_ANSWER}. Tristan set up the nightly payroll export and decided its retry policy, so he's the one to ask." ping is one short sentence to that person that starts with the literal text {{person}} (the app replaces it with their name) and asks the question in your own words, for example: "{{person}}, do you know when the export starts?" why_them is one short sentence naming their related work. sources lists up to 3 related facts, closest first.

When no fact is related at all: answered=false, answer says nothing in Knowly covers this yet, sources is empty, and ask_person, why_them and ping are null."""


def answer(question: str, asker: str, base_url: str, timeout: int = 90) -> dict:
    store = StoreClient(base_url)
    try:
        with tempfile.TemporaryDirectory(prefix="knowly-agent-") as cwd:
            config = Path(cwd) / "mcp.json"
            config.write_text(json.dumps({"mcpServers": {"knowly": {
                "type": "stdio",
                "command": sys.executable,
                "args": ["-m", "knowly.agent.tools"],
                "env": {"KNOWLY_STORE_URL": base_url, "PYTHONPATH": str(Path(__file__).resolve().parents[2])},
            }}}))
            # KNOWLY_CAPTURE_CHILD keeps the capture hook from recording the agent's own session.
            done = subprocess.run(
                ["claude", "-p", f"Question from {asker}:\n{question}", "--model", "haiku",
                 "--system-prompt", SYSTEM, "--output-format", "json", "--json-schema", json.dumps(SCHEMA),
                 "--strict-mcp-config", "--mcp-config", str(config), "--tools", "", "--allowedTools", *TOOLS,
                 "--permission-mode", "dontAsk", "--disable-slash-commands", "--no-session-persistence"],
                cwd=cwd, env={**os.environ, "KNOWLY_CAPTURE_CHILD": "1"}, capture_output=True, text=True,
                timeout=timeout, stdin=subprocess.DEVNULL,
            )
        out = json.loads(done.stdout)["structured_output"]
        result = {
            "answered": out["answered"] is True,
            "answer": str(out["answer"]).strip(),
            "sources": [{k: str(s[k]) for k in SOURCE_KEYS} for s in out["sources"][:5]],
            "ask_person": out["ask_person"] or None,
            "why_them": out["why_them"] or None,
            "ping": out.get("ping") if "{person}" in (out.get("ping") or "") else None,
        }
        if not result["answer"]:
            raise ValueError("empty answer")
    except Exception as error:  # noqa: BLE001
        print(f"knowly agent failed, using the store search: {type(error).__name__}: {error}", file=sys.stderr)
        return _fallback(question, asker, store)
    if result["answered"]:
        result["ask_person"] = result["why_them"] = result["ping"] = None
        return result
    try:
        known = {person_key(r["person"]): r["person"] for r in store.rows()}
        chosen = known.get(person_key(result["ask_person"] or ""))
        mine = chosen is not None and person_key(chosen) == person_key(asker)
        result["ask_person"] = chosen
        if chosen is None or mine:
            picked = _fallback(question, asker, store)
            # The asker stays only when nobody else has related facts.
            if picked["ask_person"] or not mine:
                result.update({k: picked[k] for k in ("answer", "ask_person", "why_them", "ping")})
    except Exception as error:  # noqa: BLE001
        print(f"knowly could not check ask_person: {type(error).__name__}", file=sys.stderr)
    if result["ask_person"] and not result["ping"]:
        result["ping"] = PING.format(person="{person}", asker=asker.title(), question=question)
    return result


def _fallback(question: str, asker: str, store: StoreClient) -> dict:
    try:
        facts = [f for f in store.search(question) if f["match"] == "who_knows"]
    except Exception as error:  # noqa: BLE001
        print(f"knowly fallback search failed: {type(error).__name__}", file=sys.stderr)
        facts = []
    them = next((f for f in facts if person_key(f["person"]) != person_key(asker)), None)
    if them:
        name = them["person"].title()
        text = f"{NO_ANSWER}. {name} worked on {them['task'] or them['topic']}, so {name} is the closest person to ask."
    else:
        text = f"{NO_ANSWER}, and nobody has recorded related work."
    return {
        "answered": False,
        "answer": text,
        "sources": [{"person": f["person"], "task": f["task"] or f["topic"], "at": f["at"][:10], "why": f["why"]} for f in facts[:3]],
        "ask_person": them["person"] if them else None,
        "why_them": f"{them['person'].title()} worked on {them['task'] or them['topic']}." if them else None,
        "ping": PING.format(person="{person}", asker=asker.title(), question=question) if them else None,
    }
