import json

from standin.classify import build_command, build_prompt, parse_output


def test_command_never_persists_sessions():
    cmd = build_command({"type": "object"})
    assert "--no-session-persistence" in cmd and cmd[cmd.index("--model") + 1] == "haiku"


def test_parse_structured_and_text():
    items = [{"key": "k1", "topic": "aikido-security-scan", "human_role": "decided", "why": None, "actor": "human"}]
    assert parse_output(json.dumps({"structured_output": {"items": items}})) == items
    assert parse_output(json.dumps({"result": "Here you go:\n" + json.dumps(items)})) == items


def test_prompt_contains_turns_and_hints():
    p = build_prompt([{"key": "k1", "text": "Wait, put the skills back", "context": "Removed skills"}])
    assert "k1" in p and "Wait, put the skills back" in p and "aikido-security-scan" in p


def test_to_rows_overrides_agents_and_scrubs():
    from standin.run import to_rows

    turn = {"source_id": "s1", "message_uuid": "u1", "at": "2026-10-20T09:00:00Z", "text": "x", "context": ""}
    run = {"source_id": "s1:abc", "message_uuid": "run", "at": "2026-10-20T09:05:00Z", "text": "Review"}
    unlabeled = {**turn, "message_uuid": "u2"}
    labels = {
        "s1:u1": {"key": "s1:u1", "topic": "aikido-security-scan", "human_role": "decided", "why": "mail me at a@b.com " + "x" * 300, "actor": "human"},
        "s1:abc:run": {"key": "s1:abc:run", "topic": "knowledge-clock", "human_role": "decided", "why": "because", "actor": "human"},
    }
    rows = to_rows([turn, unlabeled], [run], labels, person="wout")
    assert [r["id"] for r in rows] == ["s1:u1", "s1:abc:run"]
    assert rows[0]["why"].startswith("mail me at [redacted]") and len(rows[0]["why"]) == 200
    assert (rows[1]["actor"], rows[1]["human_role"], rows[1]["why"]) == ("agent", "accepted_as_is", None)
    assert rows[0]["source"] == "claude_session" and rows[0]["person"] == "wout"
