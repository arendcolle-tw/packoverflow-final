from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.helpers import row, write


@pytest.fixture
def client(tmp_path, monkeypatch):
    signals = write(tmp_path, "signals.json", [
        row(human_role="accepted_as_is", at="2026-10-20T09:00:00Z"),
        row(why="<script>alert(1)</script>", at="2026-10-20T10:00:00Z"),
    ])
    monkeypatch.setenv("KC_SIGNALS", str(signals))
    monkeypatch.setenv("KC_ALIASES", str(tmp_path / "none.json"))
    from knowledge_clock.server import app
    return TestClient(app)


def test_summary_and_topics(client):
    s = client.get("/api/summary").json()
    assert s["ai_count"] == 1 and s["human_count"] == 1 and s["skipped"] == 0
    assert s["now"] == "2026-10-20T14:15:00+00:00"
    assert [t["topic"] for t in client.get("/api/topics").json()] == ["aikido"]


def test_detail_404_and_raw_why(client):
    assert client.get("/api/topics/nope").status_code == 404
    assert client.get("/api/topics/aikido").json()["signals"][0]["why"] == "<script>alert(1)</script>"


def test_page_never_injects_html(client):
    html = (Path(__file__).parents[1] / "knowledge_clock/static/index.html").read_text()
    assert "innerHTML" not in html and "/api/summary" in html
    assert client.get("/").status_code == 200
