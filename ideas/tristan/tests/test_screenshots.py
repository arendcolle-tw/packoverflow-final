import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from knowly.recorder import screenshots

TRANSCRIPT = {
    "app": "Copilot",
    "title": "Pick a queue",
    "turns": [
        {"speaker": "assistant", "text": "Want me to set up Kafka for the events?", "time": None},
        {"speaker": "human", "text": "No, use SQS because we already run everything on AWS. Mail me at a@b.com", "time": "2:05 PM"},
        {"speaker": "assistant", "text": "Done, SQS it is.", "time": "2:06 PM"},
        {"speaker": "human", "text": "  ", "time": None},
        {"speaker": "system", "text": "Copilot may make mistakes", "time": None},
        {"speaker": "human", "text": "thanks, write the terraform", "time": None},
    ],
}
TAKEN = datetime(2026, 10, 20, 15, 30, tzinfo=timezone(timedelta(hours=2)))


def _variant(word):
    return {**TRANSCRIPT, "turns": [{**t, "text": f"{t['text']} {word}" if t["text"].strip() else t["text"]} for t in TRANSCRIPT["turns"]]}


@pytest.fixture(autouse=True)
def brussels_time(monkeypatch):
    # Shown times combine with the file's local date, so pin the local zone.
    monkeypatch.setenv("TZ", "Europe/Brussels")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_transcript_items_pair_human_turns_with_the_assistant_before():
    items = screenshots.transcript_items(TRANSCRIPT["turns"], "ab" * 32, TAKEN, "tristan")
    assert [(i["message_uuid"], i["session"], i["source_id"]) for i in items] == [
        ("t1", "shot-abababababab", "shot-abababababab"), ("t5", "shot-abababababab", "shot-abababababab")]
    assert all(re.fullmatch(r"shot-turn-[0-9a-f]{16}", i["key"]) for i in items) and items[0]["key"] != items[1]["key"]
    assert items[0]["context"] == "Want me to set up Kafka for the events?" and items[1]["context"] == "Done, SQS it is."
    assert "a@b.com" not in items[0]["text"] and "[redacted]" in items[0]["text"]
    assert [i["at"] for i in items] == ["2026-10-20T12:05:00Z", "2026-10-20T13:30:00Z"]
    assert not any(i["is_agent"] for i in items)


def test_a_shown_time_later_than_the_screenshot_is_from_the_day_before():
    assert screenshots.shown_at("16:10", TAKEN) == "2026-10-19T14:10:00Z"
    assert screenshots.shown_at("12:10 a.m.", TAKEN) == "2026-10-19T22:10:00Z"


@pytest.fixture
def fake_claude(monkeypatch):
    calls = SimpleNamespace(reads=[], prompts=[], fail_reads=0, transcripts={})

    def run(args, input, cwd, env, **kwargs):
        assert env["RECORDER_CHILD"] == "1" and args[:2] == ["claude", "-p"]
        schema = json.loads(args[args.index("--json-schema") + 1])
        if "turns" in schema["properties"]:
            tools = args[args.index("--tools") + 1]
            [image] = Path(cwd).iterdir()
            calls.reads.append({"tools": tools, "allowed": args[args.index("--allowedTools") + 1], "cwd": cwd,
                                "image": image.read_bytes(), "prompt": input})
            if calls.fail_reads:
                calls.fail_reads -= 1
                raise subprocess.CalledProcessError(1, args)
            transcript = calls.transcripts.get(image.read_bytes(), TRANSCRIPT)
            return SimpleNamespace(stdout=json.dumps({"structured_output": transcript}))
        calls.prompts.append(input)
        items = [{"key": key, "topic": "Message Queue", "human_role": "explained_why", "actor": "human",
                  "why": "because we already run everything on AWS" if "AWS" in text else "because it is cheaper"}
                 for key, text in re.findall(r"^key: (\S+)\n[^\n]*\nperson wrote: ([^\n]*)$", input, re.MULTILINE)]
        return SimpleNamespace(stdout=json.dumps({"structured_output": {"task": "pick a message queue", "items": items}}))

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def _image(folder, name, content):
    path = folder / name
    path.write_bytes(content)
    old = datetime(2026, 10, 1, 15, 30, tzinfo=UTC).timestamp()
    os.utime(path, (old, old))
    return path


def test_record_reads_each_image_once_by_content_hash(fake_claude, tmp_path):
    shots = tmp_path / "shots"
    shots.mkdir()
    _image(shots, "a.png", b"png-one")
    _image(shots, "copy of a.PNG", b"png-one")
    _image(shots, "b.webp", b"webp-two")
    _image(shots, "notes.txt", b"not an image")
    _image(shots, ".hidden.png", b"half written")
    fake_claude.transcripts.update({b"webp-two": _variant("for billing"), b"jpeg-three": _variant("for payroll")})
    state, out = tmp_path / "state.json", tmp_path / "out.json"

    rows, done = screenshots.record(shots, "tristan", out, state_path=state)
    assert done == 2 and sorted(r["image"] for r in fake_claude.reads) == [b"png-one", b"webp-two"]
    assert {(r["tools"], r["allowed"]) for r in fake_claude.reads} == {("Read", "Read")}
    assert all(str(shots) not in r["cwd"] and r["cwd"] in r["prompt"] for r in fake_claude.reads)
    assert all("copilot chat screenshot" in p and "the assistant said before: Done, SQS it is." in p for p in fake_claude.prompts)

    assert json.loads(out.read_text()) == rows and len(rows) == 4
    first = sorted((r for r in rows if r["source_id"] == "shot-" + hashlib.sha256(b"png-one").hexdigest()[:12]), key=lambda r: r["at"])
    assert [r["why"] for r in first] == ["because we already run everything on AWS", None]
    assert first[0] == {
        "id": first[0]["id"], "person": "tristan", "topic": "message-queue", "source": "screenshot",
        "source_id": first[0]["source_id"], "at": "2026-10-01T12:05:00Z", "human_role": "explained_why",
        "why": "because we already run everything on AWS", "actor": "human", "task": "pick a message queue", "app": "copilot",
    }
    assert re.fullmatch(r"shot-turn-[0-9a-f]{16}", first[0]["id"])

    _image(shots, "c.jpeg", b"jpeg-three")
    rows, done = screenshots.record(shots, "tristan", out, state_path=state)
    assert done == 1 and len(fake_claude.reads) == 3 and len(rows) == 6
    assert screenshots.record(shots, "tristan", out, state_path=state)[1] == 0 and len(fake_claude.reads) == 3


def test_a_retaken_or_overlapping_capture_does_not_duplicate_turns(fake_claude, tmp_path):
    shots = tmp_path / "shots"
    shots.mkdir()
    _image(shots, "a.png", b"png-one")
    _image(shots, "scrolled.png", b"png-scrolled")
    # The scrolled capture starts at the human turn, so the assistant message before it is out of frame.
    scrolled = TRANSCRIPT["turns"][1:] + [{"speaker": "human", "text": "Thanks, write the  terraform!", "time": None}]
    fake_claude.transcripts[b"png-scrolled"] = {**TRANSCRIPT, "turns": scrolled}

    rows, done = screenshots.record(shots, "tristan", tmp_path / "out.json", state_path=tmp_path / "state.json")
    assert done == 2 and len(rows) == 2 and len({r["id"] for r in rows}) == 2

    assert [r["human_role"] for r in rows] == ["explained_why", "explained_why"]
    assert [r["why"] for r in rows if r["why"]] == ["because we already run everything on AWS"]

    bob = screenshots.transcript_items(TRANSCRIPT["turns"], "ab" * 32, TAKEN, "bob")
    assert {i["key"] for i in bob}.isdisjoint(r["id"] for r in rows)


def test_an_unreadable_image_does_not_stop_the_scan(fake_claude, tmp_path, monkeypatch):
    shots = tmp_path / "shots"
    shots.mkdir()
    _image(shots, "a.png", b"png-one")
    _image(shots, "locked.png", b"png-locked")
    read_bytes = Path.read_bytes

    def locked(path):
        if path.name == "locked.png":
            raise PermissionError(13, "Permission denied", str(path))
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", locked)
    rows, done = screenshots.record(shots, "tristan", tmp_path / "out.json", state_path=tmp_path / "state.json")
    assert done == 1 and len(rows) == 2 and [r["image"] for r in fake_claude.reads] == [b"png-one"]


def test_a_failed_read_is_retried_on_the_next_run(fake_claude, tmp_path):
    shots = tmp_path / "shots"
    shots.mkdir()
    _image(shots, "a.png", b"png-one")
    state, out = tmp_path / "state.json", tmp_path / "out.json"
    fake_claude.fail_reads = 1
    failed = set()
    assert screenshots.record(shots, "tristan", out, state_path=state, failed=failed) == ([], 0)
    assert len(failed) == 1 and not state.exists()
    assert screenshots.record(shots, "tristan", out, state_path=state, failed=failed)[1] == 0
    assert len(screenshots.record(shots, "tristan", out, state_path=state)[0]) == 2


def test_a_file_still_being_written_waits_for_the_next_poll(fake_claude, tmp_path):
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "fresh.png").write_bytes(b"png-one")
    assert screenshots.record(shots, "tristan", tmp_path / "out.json", state_path=tmp_path / "state.json")[1] == 0
    assert fake_claude.reads == []


def test_main_pushes_the_rows(fake_claude, tmp_path, monkeypatch, capsys):
    shots = tmp_path / "shots"
    shots.mkdir()
    _image(shots, "a.png", b"png-one")
    pushed = []
    monkeypatch.setattr(screenshots, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(screenshots, "push", lambda rows, url, token: pushed.append((rows, url, token)) or (len(rows), 0))
    out = tmp_path / "out.json"
    monkeypatch.setattr(sys, "argv", ["screenshots", "--person", " Tristan ", "--dir", str(shots), "--out", str(out),
                                      "--push", "http://store", "--token", "tok"])
    screenshots.main()
    [(rows, url, token)] = pushed
    assert (len(rows), url, token) == (2, "http://store", "tok") and {r["person"] for r in rows} == {"tristan"}
    assert "2 stored, 0 skipped" in capsys.readouterr().out
