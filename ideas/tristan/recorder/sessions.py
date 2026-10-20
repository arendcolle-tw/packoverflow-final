import json
import re
from pathlib import Path

# Parsing rules copied from ideas/wout/standin/sessions.py, except that this copy skips /compact summaries and scrubs more token formats.
PASTED = re.compile(r"<pasted_content\b[^>]*>.*?</pasted_content>", re.DOTALL)
SECRETS = re.compile(
    r"sk-[A-Za-z0-9_-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}|glpat-[\w-]{20,}"
    r"|xox[a-z]-[A-Za-z0-9-]+|xapp-[A-Za-z0-9-]+|AKIA[0-9A-Z]{16}|AIza[\w-]{35}|hooks\.slack\.com/services/\S+"
    r"|eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}|[rs]k_(?:live|test)_\w{10,}|(?i:bearer)\s+[\w.~+/=-]{16,}"
    r"|(?i:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|token)\w*\s*[=:]\s*\S+"
    r"|ATATT[\w-]{20,}|npm_\w{30,}|hf_\w{30,}|ya29\.[\w-]+"
    r"|wk_[\w-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"
    r"|(?<=://)[^\s:/@]+:[^\s@/]+(?=@)"
    r"|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)
COMPACT_SUMMARY = "This session is being continued from a previous conversation"


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
                context = scrub(text[-400:])
            continue
        # A /compact summary is a "user" record that Claude wrote.
        if record.get("type") != "user" or record.get("isMeta") or record.get("isCompactSummary") or not text:
            continue
        text = PASTED.sub("[pasted]", text).strip()
        if not text or text.startswith(("<", COMPACT_SUMMARY)):
            continue
        turns.append({
            "source_id": record["sessionId"],
            "message_uuid": record["uuid"],
            "at": record["timestamp"],
            "text": scrub(text),
            "context": context,
            "is_agent": False,
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
            "text": scrub(text[:1500]),
            "context": "",
            "is_agent": True,
        })
    return runs


def session_items(session_file: Path) -> list[dict]:
    items = human_turns(session_file) + subagent_runs(session_file.with_suffix(""))
    return [{**i, "key": f"{i['source_id']}:{i['message_uuid']}", "session": session_file.stem} for i in items]


def session_files(projects_dir: Path, match: str) -> list[Path]:
    return [f for project in sorted(projects_dir.glob(f"*{match}*")) for f in sorted(project.glob("*.jsonl"))]
