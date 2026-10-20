import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowly.store import build_router, gaps, open_store

ADMIN = "a" * 40


@pytest.fixture
def store(tmp_path):
    return open_store(tmp_path)


@pytest.fixture
def client(store):
    app = FastAPI()
    app.include_router(build_router(store, ADMIN), prefix="/store")
    return TestClient(app, base_url="http://testserver/store")


@pytest.fixture
def admin():
    return {"Authorization": f"Bearer {ADMIN}"}


@pytest.fixture
def join(client, admin):
    def member_headers(person):
        response = client.post("/members", json={"person": person}, headers=admin)
        assert response.status_code == 200
        return {"Authorization": f"Bearer {response.json()['token']}"}

    return member_headers


def fact(i, person, topic, role="decided", why=None, task=None, at="2026-10-18T09:00:00Z"):
    return {"id": f"d{i}", "person": person, "topic": topic, "source": "claude_session", "source_id": f"ds{i}",
            "at": at, "human_role": role, "why": why, "task": task, "actor": "human"}


@pytest.fixture
def demo(store):
    store.add_facts([
        fact(1, "alberic", "aikido-scan", task="Run the Aikido scan on the published repo"),
        fact(2, "alberic", "payroll-export", role="corrected"),
        fact(3, "alberic", "pc-200-indexation", why="indexation of wages in joint committee 200"),
        fact(4, "jan", "deploy", role="explained_why", why="deploy from main only, the demo runs from it"),
    ])
    store.add_member("tristan")
    store.add_artifacts([{"id": "commit-a", "kind": "commit", "author": "tristan", "at": "2026-10-19T10:00:00Z",
                          "title": "Ship the backtracking board", "body": "", "link": None}])
    gaps.find_gaps(store)
    return store
