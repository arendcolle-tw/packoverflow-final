from knowledge_clock.store import load_aliases, load_signals
from tests.helpers import row, write


def test_skips_malformed_rows(tmp_path):
    good = row()
    bad1 = {**row(), "human_role": "vibes"}
    bad2 = {**row()}
    del bad2["person"]
    bad3 = {**row(), "at": "yesterday"}
    rows, skipped = load_signals([write(tmp_path, "a.json", [good, bad1, bad2, bad3])])
    assert [r["id"] for r in rows] == [good["id"]] and skipped == 3


def test_later_file_replaces_same_source(tmp_path):
    standin = [row(id="s1:a", source_id="s1"), row(id="s2:a", source_id="s2")]
    real = [row(id="s1:x", source_id="s1")]
    rows, _ = load_signals([write(tmp_path, "standin.json", standin), write(tmp_path, "real.json", real)])
    assert sorted(r["id"] for r in rows) == ["s1:x", "s2:a"]


def test_missing_files(tmp_path):
    assert load_signals([tmp_path / "nope.json"]) == ([], 0)
    assert load_aliases(tmp_path / "nope.json") == {}


def test_unreadable_file_is_skipped(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    not_a_list = write(tmp_path, "obj.json", {"rows": []})
    good = write(tmp_path, "good.json", [row(id="g:1")])
    rows, skipped = load_signals([broken, not_a_list, good])
    assert [r["id"] for r in rows] == ["g:1"] and skipped == 2


def test_unhashable_values_are_skipped_not_crashing(tmp_path):
    rows, skipped = load_signals([write(tmp_path, "a.json", [
        {**row(), "human_role": ["decided"]}, {**row(), "source": {}}, {**row(), "actor": None}, row(id="ok:1"),
    ])])
    assert [r["id"] for r in rows] == ["ok:1"] and skipped == 3


def test_corrupt_side_files_fall_back_to_empty(tmp_path):
    from knowledge_clock.store import load_whys

    broken = tmp_path / "broken.json"
    broken.write_text("{oops")
    listy = write(tmp_path, "list.json", ["a"])
    assert load_aliases(broken) == {} and load_aliases(listy) == {}
    assert load_whys(broken) == {} and load_whys(listy) == {}
