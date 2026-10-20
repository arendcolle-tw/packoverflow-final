import json

from knowledge_clock.live_store import LiveStore
from tests.helpers import row, write


def test_rows_merge_seed_and_live_and_survive_restart(tmp_path):
    seed = write(tmp_path, "seed.json", [row(id="s:1")])
    store = LiveStore([seed], tmp_path / "live")
    store.append([row(id="mcp-1", source_id="mcp-jan-x", person="jan")])
    again = LiveStore([seed], tmp_path / "live")
    assert sorted(r["id"] for r in again.rows()) == ["mcp-1", "s:1"]


def test_members(tmp_path):
    store = LiveStore([], tmp_path / "live")
    token, person = store.create_member("  Jan ")
    assert person == "jan" and store.person_for(token) == "jan"
    assert LiveStore([], tmp_path / "live").person_for(token) == "jan"
    assert store.person_for("nope") is None and store.create_member("   ") is None


def test_corrupt_live_line_skipped(tmp_path):
    (tmp_path / "live").mkdir()
    (tmp_path / "live" / "live_signals.jsonl").write_text('{"bad"\n' + json.dumps(row(id="ok")) + "\n")
    store = LiveStore([], tmp_path / "live")
    assert [r["id"] for r in store.rows()] == ["ok"] and store.skipped == 1
