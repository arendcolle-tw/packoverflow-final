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


class FakeMirror:
    def __init__(self):
        self.blobs: dict[str, bytes] = {}

    def upload(self, path):
        self.blobs[path.name] = path.read_bytes()

    def download_all(self, data_dir):
        data_dir.mkdir(parents=True, exist_ok=True)
        for name, data in self.blobs.items():
            (data_dir / name).write_bytes(data)


def test_mirror_restores_rows_and_members_on_a_fresh_disk(tmp_path):
    mirror = FakeMirror()
    store = LiveStore([], tmp_path / "disk1", mirror=mirror)
    token, _ = store.create_member("Jan")
    store.append([row(id="mcp-1", person="jan", source_id="mcp-jan-x")])

    mirror.download_all(tmp_path / "disk2")
    fresh = LiveStore([], tmp_path / "disk2", mirror=mirror)
    assert fresh.person_for(token) == "jan" and [r["id"] for r in fresh.rows()] == ["mcp-1"]


def test_person_aliases_resolve_existing_and_new_members(tmp_path):
    store = LiveStore([], tmp_path / "live")
    token, _ = store.create_member("Wout Van Hemelrijck")
    aliased = LiveStore([], tmp_path / "live", person_aliases={"wout van hemelrijck": "wout"})
    assert aliased.person_for(token) == "wout"
    assert aliased.create_member("wout  van hemelrijck")[1] == "wout"
