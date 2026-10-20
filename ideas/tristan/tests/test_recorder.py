import fcntl
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

import recorder.hook as hook
import recorder.install as install
import recorder.run as run
from recorder.sessions import human_turns, scrub, session_items

EVENT = {
    "session_id": "s1",
    "transcript_path": "/Users/x/.claude/projects/-Users-x-packoverflow-final/s1.jsonl",
    "cwd": "/Users/x/packoverflow-final",
    "hook_event_name": "Stop",
    "stop_hook_active": False,
}


def _write_session(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _user(uuid, content, **extra):
    return {"type": "user", "sessionId": "s1", "uuid": uuid, "timestamp": "2026-10-20T10:00:00Z",
            "message": {"content": content}, **extra}


@pytest.fixture
def session(tmp_path):
    path = tmp_path / "s1.jsonl"
    _write_session(path, [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Use Redis?"}]}},
        _user("u1", "No, Postgres, because we already run it. Mail me at a@b.com"),
        _user("u2", [{"type": "tool_result", "content": "file contents"}]),
        _user("u3", "<command-name>/clear</command-name>"),
        _user("u4", "hidden", isMeta=True),
        _user("u5", "fix it <pasted_content id='x'>secret log</pasted_content>"),
    ])
    return path


def test_human_turns_keeps_only_human_text(session):
    turns = human_turns(session)
    assert [t["message_uuid"] for t in turns] == ["u1", "u5"]
    assert "[redacted]" in turns[0]["text"] and "a@b.com" not in turns[0]["text"]
    assert turns[0]["context"] == "Use Redis?"
    assert turns[1]["text"] == "fix it [pasted]"


def test_human_turns_skip_compact_summaries(tmp_path):
    path = tmp_path / "s1.jsonl"
    summary = "This session is being continued from a previous conversation that ran out of context. The user said: because CI must stay green."
    _write_session(path, [
        _user("u1", "keep CI green"),
        _user("u2", summary, isCompactSummary=True, isVisibleInTranscriptOnly=True),
        _user("u3", summary),
    ])
    assert [t["message_uuid"] for t in human_turns(path)] == ["u1"]


# Samples are joined at runtime so no token-shaped literal sits in the repo.
@pytest.mark.parametrize("parts", [
    ("xapp-", "1-A07ABCDEF12-1234567890123-" + "a" * 64),
    ("github_pat_", "11ABC" * 8),
    ("glpat-", "AbCdEfGhIjKlMnOpQrSt"),
    ("gho_", "16C7e42F" * 5),
    ("ghs_", "16C7e42F" * 5),
    ("AIza", "SyA" + "1234" * 8),
    ("https://hooks.slack.com/", "services/T0000/B0000/" + "X" * 24),
    ("postgres://admin:", "hunter2@localhost:5432/app"),
    ("wk_", "a1B2c3D4" * 4),
    ("-----BEGIN OPENSSH ", "PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjE\n-----END OPENSSH PRIVATE KEY-----"),
    ("eyJhbGciOiJIUzI1NiJ9.", "eyJzdWIiOiJ0In0.c2lnbmF0dXJlZmFr"),
    ("sk_live_", "4eC39HqLyjWD" * 2),
    ("rk_test_", "4eC39HqLyjWD" * 2),
    ("Authorization: Bearer ", "9f8e7d6c5b4a" * 3),
    ("aws_secret_access_key=", "wJalrXUtnFEM" + "K7MDENG" * 4),
    ("password=", "Tulip-Orbit-58"),
    ("API_KEY: ", "Zq81Lp02Xc93"),
    ("ATATT", "3xFfGF0" + "a1B2" * 8),
    ("npm_", "a1B2c3" * 6),
    ("hf_", "a1B2c3" * 6),
    ("ya29.", "a0AfB_byC" + "x9" * 10),
])
def test_scrub_redacts_tokens_before_they_reach_a_why(parts):
    secret = "".join(parts)
    text = scrub(f"use {secret} because socket mode needs the app token")
    assert "[redacted]" in text and parts[1][:12] not in text
    assert parts[1][:12] not in (run.verbatim_why(f"use {secret} because socket mode", text) or "")


def test_scrub_keeps_prose_about_tokens_and_passwords():
    text = "we use the bearer token approach because the password expired"
    assert scrub(text) == text


def test_verbatim_why_rejects_paraphrase():
    text = "No, Postgres,  because we already\nrun it."
    assert run.verbatim_why('"because we already run it"', text) == "because we already run it"
    assert run.verbatim_why("because Postgres is cheaper", text) is None
    assert run.verbatim_why(None, text) is None


def test_to_rows_marks_agent_runs_and_skips_bad_labels():
    items = [
        {"key": "s1:u1", "source_id": "s1", "message_uuid": "u1", "at": "2026-10-20T10:00:00Z",
         "text": "go with Postgres because we run it", "is_agent": False, "session": "s1"},
        {"key": "s1:a1:run", "source_id": "s1:a1", "message_uuid": "run", "at": "2026-10-20T10:01:00Z",
         "text": "search the repo", "is_agent": True, "session": "s1"},
        {"key": "s1:u2", "source_id": "s1", "message_uuid": "u2", "at": "2026-10-20T10:02:00Z",
         "text": "ok", "is_agent": False, "session": "s1"},
    ]
    labels = {
        "s1:u1": {"topic": "Database Choice", "human_role": "decided", "why": "because we run it", "actor": "human"},
        "s1:a1:run": {"topic": "repo", "human_role": "decided", "why": "x", "actor": "human"},
        "s1:u2": {"topic": "db", "human_role": "approved", "why": None, "actor": "human"},
    }
    rows = run.to_rows(items, labels, {"s1": "pick a database"}, "tristan")
    assert [(r["id"], r["topic"], r["human_role"], r["actor"], r["why"]) for r in rows] == [
        ("s1:u1", "database-choice", "decided", "human", "because we run it"),
        ("s1:a1:run", "repo", "accepted_as_is", "agent", None),
    ]
    assert {r["task"] for r in rows} == {"pick a database"}


def test_record_only_labels_new_turns(session, tmp_path, monkeypatch):
    calls = []

    def fake_classify(items, workers):
        calls.append([i["key"] for i in items])
        return ({i["key"]: {"topic": "db", "human_role": "decided", "why": None, "actor": "human"} for i in items},
                {"s1": "pick a database"})

    monkeypatch.setattr(run, "classify", fake_classify)
    cache, out = tmp_path / "cache.json", tmp_path / "out.json"
    run.record([session], "tristan", out, cache_path=cache)
    run.record([session], "tristan", out, cache_path=cache)
    assert calls == [[i["key"] for i in session_items(session)]]
    assert len(json.loads(out.read_text())) == 2


@pytest.fixture
def store_server():
    received, reply = [], {"status": 200, "graph": True}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            rows = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append({"path": self.path, "auth": self.headers["Authorization"], "rows": rows})
            # /signals answers like the knowledge graph, /api/signals like the whoknows server.
            ok = {"added": len(rows), "updated": 0, "rejected": []} if self.path == "/signals" else {"stored": len(rows), "skipped": 0}
            status = 404 if reply["status"] == 200 and not reply["graph"] and self.path == "/signals" else reply["status"]
            body = json.dumps(ok if status == 200 else {"detail": "missing or unknown token"}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield SimpleNamespace(url=f"http://127.0.0.1:{server.server_port}", received=received, reply=reply)
    server.shutdown()
    server.server_close()


def test_push_sends_chunks_with_bearer_token(store_server):
    rows = [{"id": str(n)} for n in range(2500)]
    assert run.push(rows, store_server.url + "/", "tok") == (2500, 0)
    assert [len(r["rows"]) for r in store_server.received] == [1000, 1000, 500]
    assert {(r["path"], r["auth"]) for r in store_server.received} == {("/signals", "Bearer tok")}


def test_push_falls_back_to_the_old_store(store_server):
    store_server.reply["graph"] = False
    assert run.push([{"id": str(n)} for n in range(1500)], store_server.url, "tok") == (1500, 0)
    assert [r["path"] for r in store_server.received] == ["/signals", "/api/signals", "/api/signals"]


def test_push_path_selects_the_endpoint(store_server):
    assert run.push([{"id": "1"}], store_server.url, "tok", "api/signals") == (1, 0)
    assert store_server.received[0]["path"] == "/api/signals"


def test_main_pushes_rows_and_failed_push_exits_nonzero_keeping_rows(store_server, tmp_path, monkeypatch, capsys):
    rows = [{"id": "s1:u1"}]
    out = tmp_path / "rows.json"

    def fake_record(files, person, out, workers):
        out.write_text(json.dumps(rows))
        return rows

    monkeypatch.setattr(run, "record_summaries", fake_record)
    monkeypatch.setenv("WHOKNOWS_TOKEN", "envtok")
    argv = ["run", "--person", "tristan", "--projects-dir", str(tmp_path), "--out", str(out), "--push", store_server.url]
    monkeypatch.setattr(sys, "argv", argv)
    run.main()
    assert (store_server.received[0]["path"], store_server.received[0]["auth"]) == ("/signals", "Bearer envtok")
    assert "1 stored, 0 skipped" in capsys.readouterr().out

    out.unlink()
    store_server.reply["status"] = 401
    with pytest.raises(SystemExit) as exited:
        run.main()
    assert "HTTP 401" in str(exited.value.code) and "missing or unknown token" in str(exited.value.code)
    assert json.loads(out.read_text()) == rows


@pytest.fixture
def hook_env(tmp_path, monkeypatch):
    config = tmp_path / "recorder.json"
    config.write_text(json.dumps({"person": "tristan", "push_url": "http://store", "token": "tok"}))
    monkeypatch.setenv("WHOKNOWS_RECORDER_CONFIG", str(config))
    monkeypatch.delenv("RECORDER_CHILD", raising=False)
    monkeypatch.setattr(hook, "STATE", tmp_path / "state")
    monkeypatch.setattr(hook, "LOG", tmp_path / "state" / "hook.log")
    spawned = []
    monkeypatch.setattr(hook.subprocess, "Popen", lambda args, **kwargs: spawned.append((args, kwargs)))
    return SimpleNamespace(config=config, spawned=spawned)


@pytest.mark.parametrize("case, spawns", [
    ("matching cwd", True),
    ("matching transcript only", True),
    ("other project", False),
    ("classifier child", False),
    ("no config", False),
])
def test_hook_filters(hook_env, monkeypatch, case, spawns):
    event = dict(EVENT)
    if case == "matching transcript only":
        event["cwd"] = "/Users/x/elsewhere"
    if case == "other project":
        event.update(cwd="/Users/x/elsewhere", transcript_path="/Users/x/.claude/projects/-Users-x-elsewhere/s1.jsonl")
    if case == "classifier child":
        monkeypatch.setenv("RECORDER_CHILD", "1")
    if case == "no config":
        hook_env.config.unlink()
    hook.hook(event)
    assert bool(hook_env.spawned) == spawns


def test_main_turns_mode_keeps_one_row_per_turn(store_server, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(run, "record", lambda files, person, out, workers: calls.append("turns") or [{"id": "s1:u1"}])
    monkeypatch.setattr(run, "record_summaries", lambda files, person, out, workers: calls.append("summary") or [])
    monkeypatch.setattr(sys, "argv", ["run", "--person", "tristan", "--projects-dir", str(tmp_path), "--mode", "turns",
                                      "--push", store_server.url, "--push-path", "/api/signals", "--token", "tok"])
    run.main()
    assert calls == ["turns"] and store_server.received[0]["path"] == "/api/signals"


def test_hook_spawns_detached_worker_without_waiting(hook_env):
    hook.hook({**EVENT, "hook_event_name": "SessionEnd"})
    [(args, kwargs)] = hook_env.spawned
    assert args == [sys.executable, "-m", "recorder.hook", "--worker", EVENT["transcript_path"], "SessionEnd"]
    assert kwargs["start_new_session"] is True and kwargs["cwd"] == hook.ROOT
    assert kwargs["stdout"].name == kwargs["stderr"].name == str(hook.LOG)
    assert kwargs["stdin"] == subprocess.DEVNULL


def test_hook_main_logs_errors_instead_of_failing(hook_env, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["hook"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    hook.main()
    assert "JSONDecodeError" in hook.LOG.read_text()


def test_worker_waits_while_another_worker_holds_the_session_lock(hook_env, session, monkeypatch):
    calls = []
    monkeypatch.setattr(run, "record_summaries",
                        lambda files, person, out, cache_path: calls.append((files, person, out)) or [{"id": "s1:summary"}])
    monkeypatch.setattr(run, "push", lambda rows, url, token, path: calls.append((rows, url, token, path)) or (1, 0))
    transcript = session
    (hook.STATE / "locks").mkdir(parents=True)
    with open(hook.STATE / "locks" / "s1.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        waiting = threading.Thread(target=hook.work, args=(transcript,))
        waiting.start()
        waiting.join(0.3)
        assert waiting.is_alive() and calls == []
    waiting.join(5)
    assert not waiting.is_alive()
    assert calls == [
        ([transcript], "tristan", hook.STATE / "sessions" / "s1.json"),
        ([{"id": "s1:summary"}], "http://store", "tok", "/signals"),
    ]


def test_worker_forgets_the_session_when_the_push_fails_so_the_next_stop_resends(hook_env, session, monkeypatch):
    summaries = hook.STATE / "summaries.json"

    def summarise(files, person, out, cache_path):
        run.locked_update(cache_path, lambda path: {"s1": {"sha256": "x", "summarised_at": 0, "row": {}}})
        return [{"id": "s1:summary"}]

    def failing_push(rows, url, token, path):
        raise OSError("store down")

    monkeypatch.setattr(run, "record_summaries", summarise)
    monkeypatch.setattr(run, "push", failing_push)
    with pytest.raises(OSError):
        hook.work(session)
    assert "s1" not in run.load_summaries(summaries)


def test_hook_end_to_end_summarises_and_pushes_in_the_background(session, store_server, tmp_path):
    home = tmp_path / "home"
    transcript = home / ".claude" / "projects" / "-Users-x-packoverflow-final" / "s1.jsonl"
    transcript.parent.mkdir(parents=True)
    shutil.copy(session, transcript)
    config = tmp_path / "recorder.json"
    config.write_text(json.dumps({"person": "tristan", "push_url": store_server.url, "token": "tok"}))
    # A fake claude first on PATH, so the test never reaches a real model. It answers only when run as a recorder child.
    summary = {"title": "pick a database", "topic": "database", "role": "decided",
               "summary": 'Chose Postgres over Redis "because we already run it"'}
    fake_claude = tmp_path / "bin" / "claude"
    fake_claude.parent.mkdir()
    fake_claude.write_text(f'#!/bin/sh\ncat > /dev/null\n[ "$RECORDER_CHILD" = 1 ] || exit 1\n'
                           f"echo '{json.dumps({'structured_output': summary})}'\n")
    fake_claude.chmod(0o755)
    env = {**os.environ, "HOME": str(home), "WHOKNOWS_RECORDER_CONFIG": str(config),
           "PATH": f"{fake_claude.parent}:{os.environ['PATH']}"}
    env.pop("RECORDER_CHILD", None)

    started = time.monotonic()
    subprocess.run([sys.executable, "-m", "recorder.hook"], input=json.dumps({**EVENT, "transcript_path": str(transcript)}),
                   text=True, cwd=hook.ROOT, env=env, check=True, timeout=5)
    assert time.monotonic() - started < 1
    deadline = time.monotonic() + 10
    while not store_server.received and time.monotonic() < deadline:
        time.sleep(0.05)

    log = home / ".cache" / "packoverflow-recorder" / "hook.log"
    assert store_server.received, log.read_text() if log.exists() else "no hook log"
    [request] = store_server.received
    assert (request["path"], request["auth"]) == ("/signals", "Bearer tok")
    assert [(r["id"], r["why"], r["task"]) for r in request["rows"]] == [
        ("s1:summary", 'Chose Postgres over Redis "because we already run it"', "pick a database"),
    ]


def test_install_writes_private_config_and_merges_the_hook_once(tmp_path, monkeypatch, capsys):
    config = tmp_path / "cfg" / "recorder.json"
    settings = tmp_path / "settings.json"
    # A uv that fails like uv does without Python 3.13 offline: exit 2, which would keep Claude from stopping.
    fake_uv = tmp_path / "bin" / "uv"
    fake_uv.parent.mkdir()
    fake_uv.write_text("#!/bin/sh\nexit 2\n")
    fake_uv.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_uv.parent}:{os.environ['PATH']}")
    original = {"model": "opus", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo done"}]}]}}
    settings.write_text(json.dumps(original))
    monkeypatch.setenv("WHOKNOWS_RECORDER_CONFIG", str(config))
    argv = ["install", "--person", " Tristan ", "--push", "http://store/", "--token", "tok", "--settings", str(settings)]

    monkeypatch.setattr(sys, "argv", argv)
    install.main()
    assert '"Stop"' in capsys.readouterr().out and json.loads(settings.read_text()) == original

    monkeypatch.setattr(sys, "argv", argv + ["--write-settings"])
    install.main()
    install.main()
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert json.loads(config.read_text()) == {"person": "tristan", "push_url": "http://store", "push_path": "/signals",
                                              "token": "tok", "match": "packoverflow"}
    merged = json.loads(settings.read_text())
    commands = [h["command"] for group in merged["hooks"]["Stop"] for h in group["hooks"]]
    assert merged["model"] == "opus" and len(commands) == 2 and commands[0] == "echo done"
    assert commands[1].startswith(f"cd {install.ROOT} && ") and commands[1].endswith("python -m recorder.hook || true")
    assert [h["command"] for group in merged["hooks"]["SessionEnd"] for h in group["hooks"]] == [commands[1]]
    subprocess.run(["sh", "-c", commands[1]], input="{}", text=True, check=True)
    [backup] = tmp_path.glob("settings.json.bak-*")
    assert json.loads(backup.read_text()) == original
    assert "already has the Stop and SessionEnd hooks" in capsys.readouterr().out


def test_install_replaces_a_hook_from_before_the_exit_guard(tmp_path):
    settings = tmp_path / "settings.json"
    entry = {"type": "command", "command": "cd /r && uv run python -m recorder.hook || true", "timeout": 10}
    settings.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{**entry, "command": "cd /r && uv run python -m recorder.hook"}]}]}}))
    assert install.merge_hooks(settings, entry).startswith("updated the Stop hook and added the SessionEnd hook")
    hooks = json.loads(settings.read_text())["hooks"]
    assert hooks == {"Stop": [{"hooks": [entry]}], "SessionEnd": [{"hooks": [entry]}]}
