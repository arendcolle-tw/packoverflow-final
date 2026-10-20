import json
import re
from pathlib import Path

PASTED = re.compile(r"<pasted_content\b[^>]*>.*?</pasted_content>", re.DOTALL)
SECRETS = re.compile(
    r"sk-[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]+|AKIA[0-9A-Z]{16}"
    r"|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)


def _records(path: Path) -> list[dict]:
    records = []
    for line in path.read_text().splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _text(content) -> str | None:
    if isinstance(content, str):
        return content
    if not isinstance(content, list) or any(b.get("type") == "tool_result" for b in content if isinstance(b, dict)):
        return None
    parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return " ".join(parts) if parts else None


def scrub(text: str) -> str:
    return SECRETS.sub("[redacted]", text)


def human_turns(session_file: Path) -> list[dict]:
    turns, context = [], ""
    for record in _records(session_file):
        if record.get("isSidechain"):
            continue
        message = record.get("message") or {}
        text = _text(message.get("content"))
        if record.get("type") == "assistant":
            if text:
                context = text[-400:]
            continue
        if record.get("type") != "user" or record.get("isMeta") or not text:
            continue
        text = PASTED.sub("[pasted]", text).strip()
        if not text or text.startswith("<"):
            continue
        turns.append({
            "source_id": record["sessionId"],
            "message_uuid": record["uuid"],
            "at": record["timestamp"],
            "text": text,
            "context": context,
        })
    return turns


def subagent_runs(session_dir: Path) -> list[dict]:
    runs = []
    for agent_file in sorted((session_dir / "subagents").glob("**/agent-*.jsonl")):
        records = [r for r in _records(agent_file) if r.get("timestamp")]
        prompt = next((r for r in records if r.get("type") == "user"), None)
        text = _text((prompt or {}).get("message", {}).get("content")) if prompt else None
        if not text:
            continue
        runs.append({
            "source_id": f"{prompt['sessionId']}:{prompt.get('agentId') or agent_file.stem.removeprefix('agent-')}",
            "message_uuid": "run",
            "at": records[0]["timestamp"],
            "text": text[:1500],
        })
    return runs
