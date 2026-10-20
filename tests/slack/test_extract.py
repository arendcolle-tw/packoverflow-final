import json
import os
import subprocess

import pytest

from knowly.slack import extract as extract_mod
from knowly.slack.extract import extract, kebab_topic

QUESTION = "What time does the nightly payroll export start?"
ANSWER = "16:00, so three retries still finish before the bank closes the SFTP window at 18:00."


def fake_claude(monkeypatch, output: dict | None, calls: list):
    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        stdout = json.dumps({"type": "result", "is_error": False, "structured_output": output})
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(extract_mod.subprocess, "run", run)


def no_claude(monkeypatch):
    def run(cmd, **kwargs):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(extract_mod.subprocess, "run", run)


def test_extract_rephrases_the_reply_into_a_standalone_fact(monkeypatch):
    calls = []
    fake_claude(monkeypatch, {"is_answer": True, "fact": "Export starts at 16:00.", "topic": "Payroll Export_Schedule"}, calls)
    result = extract(QUESTION, ANSWER, "tristan")
    assert result == {"is_answer": True, "fact": "Export starts at 16:00.", "topic": "payroll-export-schedule"}
    cmd, kwargs = calls[0]
    assert cmd[:4] == ["claude", "-p", "--model", "haiku"]
    assert json.loads(cmd[cmd.index("--json-schema") + 1])["required"] == ["is_answer", "fact", "topic"]
    assert "--strict-mcp-config" in cmd
    assert kwargs["env"]["KNOWLY_CAPTURE_CHILD"] == "1"
    assert kwargs["cwd"] != os.getcwd()
    assert ANSWER in kwargs["input"] and ANSWER not in cmd


def test_extract_sends_a_reply_starting_with_a_dash_through_stdin(monkeypatch):
    calls = []
    fake_claude(monkeypatch, {"is_answer": True, "fact": "x", "topic": "flags"}, calls)
    extract(QUESTION, "--version is what you want, it runs at 16:00", "tristan")
    assert not any(arg.startswith("--version") for arg in calls[0][0])


def test_extract_condenses_a_long_reply_to_200(monkeypatch):
    long_reply = "It starts at 16:00. " + "We moved it because the bank closes the SFTP window at 18:00. " * 5
    condensed = 'Starts "at 16:00" because "the bank closes the SFTP window at 18:00". ' * 4
    fake_claude(monkeypatch, {"is_answer": True, "fact": condensed, "topic": "payroll-export"}, [])
    assert extract(QUESTION, long_reply, "tristan")["fact"] == condensed[:200]


def test_extract_not_an_answer_from_claude(monkeypatch):
    fake_claude(monkeypatch, {"is_answer": False, "fact": "let me check", "topic": "payroll-export"}, [])
    assert extract(QUESTION, "let me check", "tristan")["is_answer"] is False


@pytest.mark.parametrize("reply, is_answer", [
    (ANSWER, True),
    ("let me check", False),
    ("Which bank do you mean, the Belgian one?", False),
    ("thanks!", False),
])
def test_extract_fallback_without_claude(monkeypatch, reply, is_answer):
    no_claude(monkeypatch)
    result = extract(QUESTION, reply, "tristan")
    assert result == {"is_answer": is_answer, "fact": reply[:200], "topic": "nightly-payroll-export-start"}


def test_extract_fallback_on_claude_error_output(monkeypatch):
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout=json.dumps({"is_error": True, "result": "boom"}), stderr="")

    monkeypatch.setattr(extract_mod.subprocess, "run", run)
    long_reply = "word " * 60
    result = extract(QUESTION, long_reply, "tristan")
    assert result["is_answer"] is True and result["fact"] == long_reply.strip()[:200]


def test_kebab_topic():
    assert kebab_topic("Payroll Export_Schedule", QUESTION) == "payroll-export-schedule"
    assert kebab_topic("", QUESTION) == "nightly-payroll-export-start"
    assert kebab_topic("", "who?") == "slack-question"
