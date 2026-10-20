import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import to_graph  # noqa: E402

REAL = to_graph.ROOT / "ideas" / "tristan" / "data" / "signals-wout.json"


def row(**over):
    base = {"id": "s1:u1", "person": "tristan", "topic": "aikido-security-scan", "source": "claude_session",
            "source_id": "s1", "at": "2026-10-15T10:00:00Z", "human_role": "decided", "why": "because CI", "actor": "human",
            "task": "Set up the aikido security scan in CI"}
    return {**base, **over}


def test_real_recorder_output_converts_without_loss():
    rows = json.loads(REAL.read_text())
    signals, dropped = to_graph.convert(rows)
    assert dropped == [] and len(signals) == len(rows)
    assert all("person" not in s for s in signals)
    assert sum(1 for s in signals if s["why"]) == sum(1 for r in rows if r["why"])


def test_keeps_task_and_app_and_drops_person():
    signal, _ = to_graph.to_signal(row(source="screenshot", app="copilot", source_id="shot-abc"))
    assert signal["task"] == "Set up the aikido security scan in CI" and signal["app"] == "copilot"
    assert "person" not in signal


def test_rescrubs_secrets_in_why_and_task():
    signal, _ = to_graph.to_signal(row(why="use token=ghp_" + "a" * 30, task="mail me at a@b.com"))
    assert "ghp_" not in signal["why"] and "a@b.com" not in signal["task"]


def test_rejects_bad_rows_and_dedupes_on_id():
    signals, dropped = to_graph.convert([row(human_role="guessed"), row(source="email"), row(at="yesterday"),
                                         row(why="first"), row(why="second"), row(source="copilot_chat", id="c1")])
    assert len(dropped) == 3
    assert [s["why"] for s in signals if s["id"] == "s1:u1"] == ["second"] and len(signals) == 2
