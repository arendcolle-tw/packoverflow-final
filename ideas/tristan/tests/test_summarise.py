import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import recorder.hook as hook
import recorder.run as run
import recorder.summarise as summarise
from recorder.summarise import compact, guard_quotes, to_row

ALBERIC = Path(__file__).resolve().parents[2] / "alberic"
SUMMARY = {"title": "pick a database for the queue", "topic": "Database Choice", "role": "decided",
           "summary": 'Chose Postgres over Redis "because we already  RUN it." and "because it is faster"'}


def _record(kind, uuid, content, at="2026-10-20T10:00:00Z", **extra):
    return {"type": kind, "sessionId": "s1", "uuid": uuid, "timestamp": at, "cwd": "/Users/x/packoverflow-final",
            "message": {"content": content}, **extra}


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


@pytest.fixture
def session(tmp_path):
    return _write(tmp_path / "s1.jsonl", [
        {"type": "queue-operation", "timestamp": "2026-10-20T09:59:00Z"},
        _record("user", "u1", "Which store should the queue use?"),
        _record("assistant", "a1", [{"type": "thinking", "thinking": "hmm"}]),
        _record("assistant", "a2", [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]),
        _record("user", "u2", [{"type": "tool_result", "content": "TOOL OUTPUT secret.txt"}]),
        _record("assistant", "a3", [{"type": "text", "text": "Use Redis? " + "x" * 3000 + " Or Postgres?"}]),
        _record("user", "u3", "No, Postgres,  because we already\nrun it. Mail me at a@b.com", at="2026-10-20T10:05:00Z"),
        _record("user", "u4", "hidden meta", isMeta=True),
        _record("user", "u5", "This session is being continued from a previous conversation", isCompactSummary=True),
        _record("user", "u6", "<command-name>/clear</command-name>"),
        _record("user", "u7", "subagent prompt", isSidechain=True),
        _record("assistant", "a4", [{"type": "text", "text": "SIDECHAIN REPLY"}], isSidechain=True),
        _record("assistant", "a5", [{"type": "text", "text": "Done, Postgres it is."}], at="2026-10-20T10:06:00Z"),
    ])


def test_compact_keeps_human_text_verbatim_and_drops_tool_output(session):
    text = compact(session)
    assert text.startswith("Session s1\nProject: /Users/x/packoverflow-final\nFrom 2026-10-20T10:00:00Z to 2026-10-20T10:06:00Z")
    assert "Human: Which store should the queue use?" in text
    assert "Human: No, Postgres,  because we already\nrun it. Mail me at [redacted]" in text
    for gone in ("TOOL OUTPUT", "hidden meta", "continued from a previous", "/clear", "subagent prompt", "SIDECHAIN", "hmm", "Bash"):
        assert gone not in text
    [reply, done] = [block for block in text.split("\n\n") if block.startswith("Claude: ")]
    assert reply.startswith("Claude: Use Redis?") and reply.endswith("Or Postgres?") and " [...] " in reply
    assert len(reply) < 1600 and done == "Claude: Done, Postgres it is."


def test_compact_keeps_the_start_and_end_of_a_long_session(tmp_path):
    records = [_record("user" if n % 2 == 0 else "assistant", f"m{n}",
                       f"turn {n} " + "y" * 900 if n % 2 == 0 else [{"type": "text", "text": f"reply {n} " + "z" * 900}])
               for n in range(400)]
    text = compact(_write(tmp_path / "s1.jsonl", records))
    assert len(text) < 61_000 and "turns cut ...]" in text
    assert "Human: turn 0 " in text and "Claude: reply 399 " in text and "turn 200 " not in text


def test_compact_is_empty_without_human_turns(tmp_path):
    path = _write(tmp_path / "s1.jsonl", [_record("assistant", "a1", [{"type": "text", "text": "hello"}])])
    assert compact(path) == ""


def test_quote_guard_keeps_real_quotes_and_strips_invented_ones():
    said = "No, Postgres,  because we already\nrun it."
    assert guard_quotes('Chose Postgres "because we already  RUN it." over Redis', said) == \
        'Chose Postgres "because we already RUN it." over Redis'
    assert guard_quotes('Chose Postgres "because it is faster"', said) == "Chose Postgres because it is faster"
    assert guard_quotes('Chose “Postgres” and “cheap” and a stray " mark', said) == 'Chose "Postgres" and cheap and a stray mark'


def test_to_row_passes_the_knowledge_graph_validation(session, monkeypatch):
    if not (ALBERIC / "knowledge_graph" / "graph.py").exists():
        pytest.skip("ideas/alberic is not checked out")
    monkeypatch.syspath_prepend(str(ALBERIC))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec = importlib.util.spec_from_file_location("alberic_graph", ALBERIC / "knowledge_graph" / "graph.py")
    graph = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(graph)

    row = to_row(session, {**SUMMARY, "summary": SUMMARY["summary"] + " word" * 60, "title": "t" * 70 + " eleven chars"}, "tristan")
    assert graph.validate(row) is None
    assert row["why"].startswith('Chose Postgres over Redis "because we already RUN it." and because it is faster word')
    assert len(row["why"]) <= 200 and row["why"].endswith(" word") and row["task"] == "t" * 70 + " eleven"
    assert {k: row[k] for k in ("id", "person", "topic", "source", "source_id", "at", "human_role", "actor")} == {
        "id": "s1:summary", "person": "tristan", "topic": "database-choice", "source": "claude_session",
        "source_id": "s1", "at": "2026-10-20T10:05:00Z", "human_role": "decided", "actor": "human",
    }


def test_summarise_runs_haiku_without_tools_as_a_recorder_child(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout=json.dumps({"structured_output": SUMMARY}))

    monkeypatch.setattr(summarise.subprocess, "run", fake_run)
    assert summarise.summarise("Session s1\n\nHuman: hi") == SUMMARY
    [(args, kwargs)] = calls
    assert args[:9] == ["claude", "-p", "--model", "haiku", "--no-session-persistence", "--tools", "", "--output-format", "json"]
    assert json.loads(args[args.index("--json-schema") + 1])["required"] == ["title", "topic", "role", "summary"]
    assert kwargs["env"]["RECORDER_CHILD"] == "1" and kwargs["input"].endswith("Human: hi")
    assert not Path(kwargs["cwd"]).exists()


def test_record_summaries_skips_unchanged_sessions(session, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(run, "summarise", lambda text: calls.append(text) or SUMMARY)
    cache, out = tmp_path / "summaries.json", tmp_path / "out.json"
    run.record_summaries([session], "tristan", out, cache_path=cache)
    run.record_summaries([session], "tristan", out, cache_path=cache)
    assert len(calls) == 1

    with session.open("a") as f:
        f.write(json.dumps(_record("user", "u8", "and keep it on one box", at="2026-10-20T11:00:00Z")) + "\n")
    [row] = run.record_summaries([session], "tristan", out, cache_path=cache)
    assert len(calls) == 2 and row["at"] == "2026-10-20T11:00:00Z"
    assert json.loads(out.read_text()) == [row]
    assert json.loads(cache.read_text())["s1"]["sha256"] == hashlib.sha256(compact(session).encode()).hexdigest()


def test_record_summaries_keeps_the_previous_row_when_a_summary_fails(session, tmp_path, monkeypatch):
    cache, out = tmp_path / "summaries.json", tmp_path / "out.json"
    monkeypatch.setattr(run, "summarise", lambda text: SUMMARY)
    [first] = run.record_summaries([session], "tristan", out, cache_path=cache)
    with session.open("a") as f:
        f.write(json.dumps(_record("user", "u8", "one more thing")) + "\n")

    def failing(text):
        raise subprocess.CalledProcessError(1, "claude")

    monkeypatch.setattr(run, "summarise", failing)
    assert run.record_summaries([session], "tristan", out, cache_path=cache) == [first]


@pytest.fixture
def worker(tmp_path, monkeypatch, session):
    config = tmp_path / "recorder.json"
    config.write_text(json.dumps({"person": "tristan", "push_url": "http://store", "token": "tok"}))
    monkeypatch.setenv("WHOKNOWS_RECORDER_CONFIG", str(config))
    monkeypatch.setattr(hook, "STATE", tmp_path / "state")
    summarised, slept = [], []
    monkeypatch.setattr(run, "record_summaries", lambda files, person, out, cache_path: summarised.append(files) or [{"id": "s1:summary"}])
    monkeypatch.setattr(run, "push", lambda rows, url, token, path: (1, 0))
    monkeypatch.setattr(hook.time, "sleep", slept.append)

    def cached(sha256, seconds_ago):
        (tmp_path / "state").mkdir(exist_ok=True)
        (tmp_path / "state" / "summaries.json").write_text(json.dumps({"s1": {"sha256": sha256, "summarised_at": time.time() - seconds_ago}}))

    return SimpleNamespace(session=session, summarised=summarised, slept=slept, cached=cached)


def test_worker_skips_a_session_whose_text_did_not_change(worker):
    worker.cached(hashlib.sha256(compact(worker.session).encode()).hexdigest(), 3600)
    hook.work(worker.session, "SessionEnd")
    assert worker.summarised == [] and worker.slept == []


def test_worker_waits_a_minute_between_summaries_unless_the_session_ends(worker):
    worker.cached("older text", 10)
    hook.work(worker.session, "Stop")
    assert len(worker.summarised) == 1 and len(worker.slept) == 1 and 49 < worker.slept[0] <= 50

    hook.work(worker.session, "SessionEnd")
    assert len(worker.summarised) == 2 and len(worker.slept) == 1

    worker.cached("older text", 120)
    hook.work(worker.session, "Stop")
    assert len(worker.summarised) == 3 and len(worker.slept) == 1
