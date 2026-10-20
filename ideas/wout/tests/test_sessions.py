import json
from pathlib import Path

from standin.sessions import human_turns, scrub, subagent_runs


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\nnot json\n")
    return path


def _rec(type_, content, uuid, **kw):
    return {"type": type_, "sessionId": "sess-1", "uuid": uuid, "timestamp": f"2026-10-20T09:0{uuid[-1]}:00Z",
            "isSidechain": False, "message": {"role": type_, "content": content}, **kw}


def make_session(tmp_path: Path) -> Path:
    return _write_jsonl(tmp_path / "sess-1.jsonl", [
        _rec("assistant", [{"type": "text", "text": "Which stack?"}], "u1"),
        _rec("user", "We go with FastAPI because nobody picked a stack", "u2"),
        _rec("user", [{"type": "tool_result", "content": "ok"}], "u3"),
        _rec("user", "Caveat: meta", "u4", isMeta=True),
        _rec("user", "<command-name>/clear</command-name>", "u5"),
        _rec("user", "sidechain prompt", "u6", isSidechain=True),
        _rec("user", [{"type": "text", "text": "Use this: <pasted_content id=x>secret stuff\nmore</pasted_content> and keep it short"}], "u7"),
    ])


def make_subagent(tmp_path: Path) -> Path:
    session_dir = tmp_path / "sess-1"
    _write_jsonl(session_dir / "subagents" / "agent-abc.jsonl", [
        {"type": "user", "sessionId": "sess-1", "agentId": "abc", "uuid": "x1", "timestamp": "2026-10-20T09:00:00Z",
         "isSidechain": True, "message": {"role": "user", "content": "Review the design doc"}},
        {"type": "assistant", "sessionId": "sess-1", "agentId": "abc", "uuid": "x2", "timestamp": "2026-10-20T09:01:00Z",
         "isSidechain": True, "message": {"role": "assistant", "content": [{"type": "text", "text": "Done"}]}},
    ])
    return session_dir


def test_human_turns_filters(tmp_path):
    turns = human_turns(make_session(tmp_path))
    assert [t["text"] for t in turns] == [
        "We go with FastAPI because nobody picked a stack",
        "Use this: [pasted] and keep it short",
    ]
    assert turns[0]["context"] == "Which stack?" and turns[0]["source_id"] == "sess-1"
    assert turns[0]["message_uuid"] == "u2" and turns[0]["at"] == "2026-10-20T09:02:00Z"


def test_subagent_runs(tmp_path):
    runs = subagent_runs(make_subagent(tmp_path))
    assert runs == [{"source_id": "sess-1:abc", "message_uuid": "run", "at": "2026-10-20T09:00:00Z", "text": "Review the design doc"}]


def test_scrub():
    assert scrub("key sk-ant-abcdefghijkl mail wout@techwolf.ai") == "key [redacted] mail [redacted]"
