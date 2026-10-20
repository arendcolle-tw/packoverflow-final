from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowly.store import build_router


def row(i, person, topic="pc-200-indexation", role="decided", at="2026-10-01", why="indexation of wages in joint committee 200"):
    return {"id": f"r{i}", "person": person, "topic": topic, "source": "claude_session", "source_id": f"s{i}",
            "at": at, "human_role": role, "why": why if role != "accepted_as_is" else None, "actor": "human"}


def test_members_need_the_admin_token(client, store, admin):
    assert client.post("/members", json={"person": "alberic"}).status_code == 401
    assert client.post("/members", json={"person": "alberic"}, headers={"Authorization": "Bearer wrong"}).status_code == 403
    assert client.post("/members", json={"person": "alberic"}, headers=admin).status_code == 200

    app = FastAPI()
    app.include_router(build_router(store, ""), prefix="/store")
    unset = TestClient(app, base_url="http://testserver/store")
    assert unset.post("/members", json={"person": "alberic"}, headers={"Authorization": "Bearer "}).status_code == 401
    assert unset.post("/members", json={"person": "alberic"}, headers=admin).status_code == 403


def test_facts_need_a_member_token(client):
    assert client.post("/facts", json=[row(1, "alberic")]).status_code == 401
    assert client.post("/facts", json=[row(1, "alberic")], headers={"Authorization": "Bearer nope"}).status_code == 401


def test_person_comes_from_the_token(client, join):
    alberic = join("alberic")
    result = client.post("/facts", json=[row(100, "jan")], headers=alberic).json()
    assert result == {"added": 1, "updated": 0, "rejected": []}
    assert next(r for r in client.get("/rows").json() if r["id"] == "r100")["person"] == "alberic"


def test_another_member_cannot_overwrite(client, join):
    alberic, jan = join("alberic"), join("jan")
    client.post("/facts", json=[row(100, "alberic", why="mine")], headers=alberic)
    result = client.post("/facts", json=[row(100, "jan", why="hijacked")], headers=jan).json()
    assert result["rejected"] == ["row 0: id belongs to someone else"]
    assert next(r for r in client.get("/rows").json() if r["id"] == "r100")["why"] == "mine"


def test_read_endpoints(client, join):
    assert client.get("/health").json() == {"storage": "local", "rows": 0}
    client.post("/facts", headers=join("alberic"), json=[
        row(1, "alberic", topic="aikido", at="2026-10-15", why="run the aikido security scan on the published repo"),
        row(2, "alberic", topic="aikido", at="2026-10-16", role="accepted_as_is"),
    ])
    client.post("/facts", headers=join("tristan"), json=[row(3, "tristan")])
    assert client.get("/health").json() == {"storage": "local", "rows": 3}
    assert len(client.get("/rows").json()) == 3

    who = client.get("/who_knows", params={"q": "aikido security scan", "at": "2026-10-20"}).json()
    assert who["owner"] == "alberic"
    assert client.get("/who_knows", params={"q": "aikido", "at": "yesterday"}).status_code == 422

    assert client.get("/people/alberic", params={"at": "2026-10-20"}).json()["person"] == "alberic"
    risks = client.get("/risks", params={"at": "2026-10-20"}).json()
    assert {t["topic"]: t["status"] for t in risks} == {"aikido": "single_point", "pc-200-indexation": "single_point"}
