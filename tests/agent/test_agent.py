import asyncio
import io
import json
import subprocess
import urllib.error
from pathlib import Path

import pytest

from knowly import agent, client
from knowly.agent import tools
from knowly.client import StoreClient

BASE = "http://knowly.test/store"
PAYROLL_WHY = 'Set retries to 3 instead of 5 "because the bank closes the SFTP window at 18:00 and a late file is rejected anyway".'
ROWS = [
    {"id": "s1:a", "person": "tristan", "topic": "payroll-sftp-export", "source": "claude_session", "source_id": "s1",
     "at": "2026-10-14T09:00:00Z", "human_role": "decided", "actor": "human", "why": PAYROLL_WHY,
     "task": "Plan the nightly payroll SFTP export to the bank"},
    {"id": "s1:b", "person": "tristan", "topic": "payroll-sftp-export", "source": "claude_session", "source_id": "s1",
     "at": "2026-10-14T09:05:00Z", "human_role": "accepted_as_is", "actor": "human", "why": None},
    {"id": "s1:agent:c", "person": "tristan", "topic": "payroll-sftp-export", "source": "claude_session",
     "source_id": "s1:agent", "at": "2026-10-14T09:10:00Z", "human_role": "explained_why", "actor": "human",
     "why": "Files are named payroll-YYYYMMDD.csv so the bank can dedupe."},
    {"id": "s2:a", "person": "sam", "topic": "pitch-and-submission", "source": "claude_session", "source_id": "s2",
     "at": "2026-10-01T09:00:00Z", "human_role": "decided", "actor": "human", "why": "Keep the pitch under three minutes.",
     "task": "Write the pitch"},
    {"id": "s3:a", "person": "alberic", "topic": "bank-integration", "source": "claude_session", "source_id": "s3",
     "at": "2026-10-10T09:00:00Z", "human_role": "decided", "actor": "human", "why": "The bank API needs mTLS.",
     "task": "Connect the payroll export to the bank API"},
]
PEOPLE = [
    {"person": "tristan", "proficiency": 0.6, "evidence": [{"source_id": "s1", "at": "2026-10-14T09:10:00Z", "similarity": 0.41, "whys": []}]},
    {"person": "alberic", "proficiency": 0.3, "evidence": [{"source_id": "s3", "at": "2026-10-10T09:00:00Z", "similarity": 0.2, "whys": []}]},
]


@pytest.fixture
def store(monkeypatch):
    calls = []

    def urlopen(request, timeout=None):
        path = request.full_url.removeprefix(BASE)
        calls.append(path)
        if path == "/rows":
            return io.BytesIO(json.dumps(ROWS).encode())
        if path.startswith("/who_knows?"):
            people = [] if "pitch" in path or "sftp+window" in path else PEOPLE
            return io.BytesIO(json.dumps({"status": "single_point", "owner": "tristan", "people": people}).encode())
        raise AssertionError(path)

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(tools, "store", StoreClient(BASE))
    return calls


def test_search_joins_who_knows_evidence_with_rows(store):
    facts = StoreClient(BASE).search("How many times does the payroll export retry?")
    assert [(f["person"], f["why"][:20], f["match"]) for f in facts[:3]] == [
        ("tristan", PAYROLL_WHY[:20], "who_knows"),
        ("tristan", "Files are named payr", "who_knows"),
        ("alberic", "The bank API needs m", "who_knows"),
    ]
    assert facts[0]["task"] == "Plan the nightly payroll SFTP export to the bank"
    assert facts[0]["topic"] == "payroll-sftp-export" and facts[0]["at"] == "2026-10-14T09:00:00Z"
    assert facts[0]["score"] == 0.41
    assert all(f["why"] for f in facts)
    assert "/who_knows?q=How+many+times+does+the+payroll+export+retry%3F" in store


def test_search_matches_reasons_by_keyword_when_who_knows_misses(store):
    facts = StoreClient(BASE).search("sftp window")
    assert [(f["why"][:5], f["match"], f["score"]) for f in facts] == [
        ("Set r", "keyword", 1.0), ("Files", "keyword", 0.5)]


def test_mcp_tools(store):
    listed = asyncio.run(tools.server.list_tools())
    assert {t.name for t in listed} == {"search_facts", "person_facts", "recent_facts"}

    result = asyncio.run(tools.server.call_tool("person_facts", {"person": "Tristan"}))
    facts = json.loads(result.content[0].text)
    assert [f["why"][:5] for f in facts] == ["Files", "Set r"]

    recent = json.loads(tools.recent_facts(limit=2))
    assert [f["person"] for f in recent] == ["tristan", "tristan"]
    assert len(json.loads(tools.search_facts("payroll export"))) == 3


def _claude(stdout: str = "", raises: Exception | None = None):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(cmd=cmd, **kwargs)
        seen["mcp"] = json.loads(Path(cmd[cmd.index("--mcp-config") + 1]).read_text())
        if raises:
            raise raises
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    return seen, fake_run


def _output(**structured) -> str:
    return json.dumps({"type": "result", "is_error": False, "result": "", "structured_output": structured})


def test_answer_runs_claude_with_the_knowly_tools(store, monkeypatch):
    out = {"answered": True, "answer": "Three times. Tristan set it in a Claude session on 2026-10-14.",
           "sources": [{"person": "tristan", "task": "Plan the nightly payroll SFTP export to the bank", "at": "2026-10-14", "why": PAYROLL_WHY}],
           "ask_person": "sam", "why_them": "ignored"}
    seen, fake_run = _claude(_output(**out))
    monkeypatch.setattr(agent.subprocess, "run", fake_run)

    result = agent.answer("How many times does the payroll export retry?", "alberic", BASE)

    assert result == {**out, "ask_person": None, "why_them": None, "ping": None}
    cmd = seen["cmd"]
    assert cmd[:2] == ["claude", "-p"] and "alberic" in cmd[2] and "payroll export retry" in cmd[2]
    assert cmd[cmd.index("--model") + 1] == "haiku"
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == agent.SCHEMA
    assert "--strict-mcp-config" in cmd and cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--allowedTools") + 1:cmd.index("--allowedTools") + 4] == agent.TOOLS
    server = seen["mcp"]["mcpServers"]["knowly"]
    assert server["args"] == ["-m", "knowly.agent.tools"]
    assert server["env"]["KNOWLY_STORE_URL"] == BASE
    assert (Path(server["env"]["PYTHONPATH"]) / "knowly" / "agent" / "tools.py").exists()
    assert seen["env"]["KNOWLY_CAPTURE_CHILD"] == "1"
    assert "knowly-agent-" in seen["cwd"] and not Path(seen["cwd"]).exists()
    assert seen["timeout"] == 90


def test_answer_not_known_keeps_the_agents_pick(store, monkeypatch):
    out = {"answered": False, "answer": "Only the retry count is recorded.", "sources": [],
           "ask_person": "Tristan", "why_them": "Tristan planned the payroll export.",
           "ping": "{person}, do you know when the export starts?"}
    monkeypatch.setattr(agent.subprocess, "run", _claude(_output(**out))[1])

    result = agent.answer("What time does the nightly payroll export start?", "alberic", BASE)

    assert result["answered"] is False and result["answer"] == "Only the retry count is recorded."
    assert result["ask_person"] == "tristan" and result["why_them"] == "Tristan planned the payroll export."
    assert result["ping"] == "{person}, do you know when the export starts?"


def test_a_ping_without_the_placeholder_gets_the_fallback_sentence(store, monkeypatch):
    out = {"answered": False, "answer": "Only the retry count is recorded.", "sources": [],
           "ask_person": "tristan", "why_them": "x", "ping": "Tristan, do you know?"}
    monkeypatch.setattr(agent.subprocess, "run", _claude(_output(**out))[1])

    result = agent.answer("When does it start?", "albéric", BASE)

    assert result["ping"] == "{person}, Albéric is asking: “When does it start?” Do you know?"


@pytest.mark.parametrize("picked", ["alberic", "somebody", None])
def test_answer_replaces_the_asker_or_an_unknown_pick(store, monkeypatch, picked):
    out = {"answered": False, "answer": "Not recorded.", "sources": [], "ask_person": picked, "why_them": "x"}
    monkeypatch.setattr(agent.subprocess, "run", _claude(_output(**out))[1])

    result = agent.answer("What time does the nightly payroll export start?", "alberic", BASE)

    assert result["ask_person"] == "tristan"
    assert "Plan the nightly payroll SFTP export" in result["why_them"]
    assert result["answer"].startswith(agent.NO_ANSWER) and "Tristan" in result["answer"]
    assert result["ping"].startswith("{person}, Alberic is asking")


def test_answer_keeps_the_asker_when_nobody_else_knows(store, monkeypatch):
    out = {"answered": False, "answer": "Not recorded.", "sources": [], "ask_person": "sam", "why_them": "Only sam."}
    monkeypatch.setattr(agent.subprocess, "run", _claude(_output(**out))[1])

    assert agent.answer("pitch length", "sam", BASE)["ask_person"] == "sam"


@pytest.mark.parametrize("stdout", ["not json", json.dumps({"type": "result", "is_error": True, "result": "boom"}),
                                    _output(answered=True, answer="   ", sources=[], ask_person=None, why_them=None)])
def test_bad_output_falls_back_to_the_store_search(store, monkeypatch, stdout):
    monkeypatch.setattr(agent.subprocess, "run", _claude(stdout)[1])

    result = agent.answer("What time does the nightly payroll export start?", "alberic", BASE)

    assert result["answered"] is False
    assert result["sources"][0] == {"person": "tristan", "task": "Plan the nightly payroll SFTP export to the bank",
                                    "at": "2026-10-14", "why": PAYROLL_WHY}
    assert len(result["sources"]) == 3
    assert result["ask_person"] == "tristan"


def test_timeout_falls_back_and_skips_the_asker(store, monkeypatch):
    seen, fake_run = _claude(raises=subprocess.TimeoutExpired("claude", 5))
    monkeypatch.setattr(agent.subprocess, "run", fake_run)

    result = agent.answer("What time does the nightly payroll export start?", "tristan", BASE, timeout=5)

    assert seen["timeout"] == 5
    assert result["answered"] is False and result["ask_person"] == "alberic"


def test_missing_claude_and_store_down(monkeypatch):
    def down(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(client.urllib.request, "urlopen", down)
    monkeypatch.setattr(agent.subprocess, "run", _claude(raises=FileNotFoundError("claude"))[1])

    assert agent.answer("anything", "tristan", BASE) == {
        "answered": False, "answer": f"{agent.NO_ANSWER}, and nobody has recorded related work.", "sources": [],
        "ask_person": None, "why_them": None, "ping": None}
