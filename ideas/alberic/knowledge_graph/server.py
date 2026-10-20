"""HTTP API over the knowledge graph. Reads are public; writes need a member token, new members the admin token.

Run: uvicorn knowledge_graph.server:app --port 8080
Env: KG_ADMIN_TOKEN (admin), KG_DATA_DIR (where the SQLite file lives), KG_BUCKET (GCS mirror, on Cloud Run).
"""

import hmac
import os
import sys
from datetime import datetime
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from knowledge_graph.graph import KnowledgeGraph
from proficiency.score import parse_at

HERE = Path(__file__).resolve().parents[1]
SEED = HERE / "seed" / "signals-wout.json"
# Cloud Run sets K_SERVICE: keep the file in its writable /tmp and mirror it to Cloud Storage.
ON_CLOUD_RUN = "K_SERVICE" in os.environ


class NewMember(BaseModel):
    person: str = Field(min_length=1, max_length=300, pattern=r"\S")


def _make_mirror() -> tuple[object | None, str]:
    if not ON_CLOUD_RUN:
        return None, "local"
    try:
        from knowledge_graph.gcs_mirror import GcsMirror

        return GcsMirror(os.environ.get("KG_BUCKET")), "gcs"
    except Exception as error:  # noqa: BLE001
        print(f"GCS mirror unavailable, storing locally: {type(error).__name__}", file=sys.stderr)
        return None, "local"


def make_graph() -> tuple[KnowledgeGraph, str]:
    data_dir = Path(os.environ.get("KG_DATA_DIR") or ("/tmp/kg" if ON_CLOUD_RUN else HERE / "data"))
    mirror, storage = _make_mirror()
    return KnowledgeGraph(data_dir / "graph.sqlite", seed_paths=[SEED] if SEED.exists() else [], mirror=mirror), storage


GRAPH, STORAGE = make_graph()
app = FastAPI(title="knowledge-graph")


def _bearer(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    return token.strip()


def member(authorization: str | None = Header(None)) -> str:
    person = GRAPH.member(_bearer(authorization))
    if person is None:
        raise HTTPException(401, "unknown member token", headers={"WWW-Authenticate": "Bearer"})
    return person


def admin(authorization: str | None = Header(None)) -> None:
    expected = os.environ.get("KG_ADMIN_TOKEN", "")
    token = _bearer(authorization)
    if len(expected) < 32 or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(403, "admin token required")


def _at(at: str | None) -> datetime | None:
    try:
        return parse_at(at) if at else None
    except ValueError:
        raise HTTPException(422, "at is not an ISO time") from None


@app.post("/signals")
def post_signals(rows: list[dict] = Body(..., max_length=1000), person: str = Depends(member)) -> dict:
    return GRAPH.add_signals(rows, person=person)


@app.post("/members", dependencies=[Depends(admin)])
def post_members(body: NewMember) -> dict:
    person = body.person.strip()
    return {"person": person, "token": GRAPH.add_member(person)}


@app.get("/who_knows")
def get_who_knows(q: str = Query(..., min_length=1, max_length=300), at: str | None = None) -> dict:
    return GRAPH.who_knows(q, _at(at))


@app.get("/people/{person}")
def get_person(person: str, at: str | None = None) -> dict:
    return GRAPH.person_view(person, _at(at))


@app.get("/risks")
def get_risks(at: str | None = None) -> list[dict]:
    return GRAPH.risks(_at(at))


@app.get("/rows")
def get_rows() -> list[dict]:
    return GRAPH.rows()


@app.get("/health")
def health() -> dict:
    return {"storage": STORAGE, "rows": len(GRAPH.rows())}
