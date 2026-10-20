import importlib

import pytest
from fastapi.testclient import TestClient

ADMIN = "a" * 40


def row(i, person, topic="pc-200-indexation", role="decided", at="2026-10-01", why="indexation of wages in joint committee 200"):
    return {"id": f"r{i}", "person": person, "topic": topic, "source": "claude_session", "source_id": f"s{i}",
            "at": at, "human_role": role, "why": why if role != "accepted_as_is" else None, "actor": "human"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KG_ADMIN_TOKEN", ADMIN)
    monkeypatch.delenv("K_SERVICE", raising=False)
    import knowledge_graph.server as server

    return TestClient(importlib.reload(server).app)


def join(client, person):
    response = client.post("/members", json={"person": person}, headers={"Authorization": f"Bearer {ADMIN}"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_members_need_the_admin_token(client, monkeypatch):
    assert client.post("/members", json={"person": "lies"}).status_code == 401
    assert client.post("/members", json={"person": "lies"}, headers={"Authorization": "Bearer wrong"}).status_code == 403
    monkeypatch.setenv("KG_ADMIN_TOKEN", "")
    assert client.post("/members", json={"person": "lies"}, headers={"Authorization": "Bearer "}).status_code == 401
    assert client.post("/members", json={"person": "lies"}, headers={"Authorization": f"Bearer {ADMIN}"}).status_code == 403


def test_signals_need_a_member_token(client):
    assert client.post("/signals", json=[row(1, "lies")]).status_code == 401
    assert client.post("/signals", json=[row(1, "lies")], headers={"Authorization": "Bearer nope"}).status_code == 401


def test_person_comes_from_the_token(client):
    lies = join(client, "lies")
    result = client.post("/signals", json=[row(100, "jan")], headers=lies).json()
    assert result == {"added": 1, "updated": 0, "rejected": []}
    assert next(r for r in client.get("/rows").json() if r["id"] == "r100")["person"] == "lies"


def test_another_member_cannot_overwrite(client):
    lies, jan = join(client, "lies"), join(client, "jan")
    client.post("/signals", json=[row(100, "lies", why="mine")], headers=lies)
    result = client.post("/signals", json=[row(100, "jan", why="hijacked")], headers=jan).json()
    assert result["rejected"] == ["row 0: id belongs to someone else"]
    assert next(r for r in client.get("/rows").json() if r["id"] == "r100")["why"] == "mine"


def test_read_endpoints(client):
    assert client.get("/health").json() == {"storage": "local", "rows": 51}
    assert len(client.get("/rows").json()) == 51

    who = client.get("/who_knows", params={"q": "aikido security scan", "at": "2026-10-20"}).json()
    assert who["owner"] == "wout"
    assert client.get("/who_knows", params={"q": "aikido", "at": "yesterday"}).status_code == 422

    assert client.get("/people/wout", params={"at": "2026-10-20"}).json()["person"] == "wout"
    risks = client.get("/risks", params={"at": "2026-10-20"}).json()
    assert {t["status"] for t in risks} <= {"dark", "single_point", "fading", "healthy"} and risks
