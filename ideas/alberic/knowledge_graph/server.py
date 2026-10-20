"""HTTP API over the knowledge graph. Reads are public; writes need a member token, new members the admin token.

Run: uvicorn knowledge_graph.server:app --port 8080
Env: KG_ADMIN_TOKEN (admin), KG_DATA_DIR (where the SQLite file lives), KG_BUCKET (GCS mirror, on Cloud Run).
Backtracking (gaps) env: ANTHROPIC_API_KEY, ELEVENLABS_*, KG_PHONE_NUMBERS; see README.
"""

import hmac
import json
import os
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from knowledge_graph import gaps, pages, voice
from knowledge_graph.graph import KnowledgeGraph
from proficiency.score import parse_at

HERE = Path(__file__).resolve().parents[1]
SEED = HERE / "seed" / "signals-wout.json"
ARTIFACTS = HERE / "seed" / "artifacts.json"
# Cloud Run sets K_SERVICE: keep the file in its writable /tmp and mirror it to Cloud Storage.
ON_CLOUD_RUN = "K_SERVICE" in os.environ


class NewMember(BaseModel):
    person: str = Field(min_length=1, max_length=300, pattern=r"\S")


class Artifact(BaseModel):
    id: str = Field(min_length=1, max_length=300)
    kind: Literal["commit", "ticket", "doc"]
    author: str | None = Field(None, max_length=300)
    at: str = Field(max_length=40)
    title: str = Field(min_length=1, max_length=300)
    body: str = Field("", max_length=2000)
    link: str | None = Field(None, max_length=500)


class Answer(BaseModel):
    answer: str = Field(min_length=1, max_length=200, pattern=r"\S")


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
    data_dir = Path(os.environ.get("KG_DATA_DIR") or (str(Path(tempfile.gettempdir()) / "kg") if ON_CLOUD_RUN else HERE / "data"))
    mirror, storage = _make_mirror()
    return KnowledgeGraph(data_dir / "graph.sqlite", seed_paths=[SEED] if SEED.exists() else [], mirror=mirror), storage


def _load_artifacts(graph: KnowledgeGraph) -> None:
    """Seed artifacts (this repo's commits) fill ids the database does not have, then gaps are found."""
    if ARTIFACTS.exists():
        known = {a["id"] for a in graph.artifacts()}
        fresh = [a for a in json.loads(ARTIFACTS.read_text()) if a["id"] not in known]
        if fresh:
            graph.add_artifacts(fresh)
    gaps.find_gaps(graph)


GRAPH, STORAGE = make_graph()
_load_artifacts(GRAPH)
threading.Thread(target=voice.ensure_webhook, args=(GRAPH,), daemon=True).start()
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
    result = GRAPH.add_signals(rows, person=person)
    gaps.find_gaps(GRAPH)
    return result


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


# Backtracking: gaps, Claude's drafts, and the owner's answer. Drafts never enter /rows.

def _gap(gap_id: str) -> dict:
    gap = GRAPH.gap(gap_id)
    if gap is None:
        raise HTTPException(404, "no such gap")
    return gap


@app.post("/artifacts", dependencies=[Depends(admin)])
def post_artifacts(artifacts: list[Artifact] = Body(..., max_length=1000)) -> dict:
    for a in artifacts:
        _at(a.at)
    stored = GRAPH.add_artifacts([a.model_dump() for a in artifacts])
    return {"stored": stored, "open_gaps": len(gaps.find_gaps(GRAPH))}


@app.get("/gaps")
def get_gaps(status: str | None = None) -> list[dict]:
    """status=open means not answered yet (open, drafted or calling)."""
    found = gaps.all_gaps(GRAPH)
    if status == "open":
        found = [g for g in found if g["status"] in gaps.UNANSWERED]
    elif status:
        found = [g for g in found if g["status"] == status]
    return [gaps.public(g) for g in found]


@app.post("/gaps/scan", dependencies=[Depends(admin)])
def post_scan(claude: int = Query(0, ge=0, le=50)) -> dict:
    """Find gaps. With claude=N, also ask Claude to draft the N riskiest that still have a template draft."""
    found = gaps.find_gaps(GRAPH)
    drafted = 0
    for gap in [g for g in found if g.get("draft_source") != "claude"][:claude]:
        drafted += gaps.draft_gap(GRAPH, gap["id"])["draft_source"] == "claude"
    return {"open": len(found), "claude_drafts": drafted}


@app.post("/gaps/{gap_id}/draft", dependencies=[Depends(admin)])
def post_draft(gap_id: str) -> dict:
    _gap(gap_id)
    return gaps.public(gaps.draft_gap(GRAPH, gap_id))


@app.post("/gaps/{gap_id}/answer")
def post_answer(gap_id: str, body: Answer, person: str = Depends(member)) -> dict:
    gap = _gap(gap_id)
    if gap["owner"] != person:
        raise HTTPException(403, "only the owner can answer this gap")
    if gap["status"] == "answered":
        raise HTTPException(409, "already answered")
    return gaps.public(gaps.answer_gap(GRAPH, gap_id, body.answer, "gap_form", f"form-{gap_id}"))


def _callable(owners: set[str]) -> set[str]:
    """Owners we can phone: calls configured and the owner opted in with a number in KG_PHONE_NUMBERS."""
    if not all(os.environ.get(k) for k in ("ELEVENLABS_PHONE_NUMBER_ID", "ELEVENLABS_API_KEY")):
        return set()
    return {o for o in owners if o and voice.phone_number(o)}


@app.get("/gaps/board", response_class=HTMLResponse)
def get_board() -> str:
    found = gaps.all_gaps(GRAPH)
    answered = sorted((g for g in found if g["status"] == "answered"), key=lambda g: g["answered_at"] or "", reverse=True)
    waiting = [g for g in found if g["status"] in gaps.UNANSWERED]
    return pages.board(waiting, answered, phone=_callable({g["owner"] for g in waiting}), claude=bool(os.environ.get("ANTHROPIC_API_KEY")))


@app.get("/gaps/{gap_id}/talk", response_class=HTMLResponse)
def get_talk(gap_id: str) -> str:
    gap = _gap(gap_id)
    return pages.talk(gap, widget=voice.widget(gap) if gap["status"] != "answered" else "")


@app.post("/gaps/{gap_id}/call", dependencies=[Depends(admin)])
def post_call(gap_id: str) -> dict:
    """Phone the owner. 409 with the browser fallback URL when calls are not configured for them."""
    gap = _gap(gap_id)
    if gap["status"] == "answered":
        raise HTTPException(409, "already answered")
    try:
        call_id = voice.start_call(gap)
    except voice.NotConfigured as error:
        raise HTTPException(409, f"{error}; use /gaps/{gap_id}/talk") from None
    except Exception as error:  # noqa: BLE001
        print(f"outbound call failed: {type(error).__name__}", file=sys.stderr)
        raise HTTPException(502, f"call failed; use /gaps/{gap_id}/talk") from None
    gap.update(status="calling", call_id=call_id)
    GRAPH.save_gaps([gap])
    return gaps.public(gap)


@app.post("/webhooks/elevenlabs")
async def post_webhook(request: Request) -> dict:
    body = await request.body()
    if not voice.verify(request.headers.get("elevenlabs-signature"), body, voice.webhook_secret(GRAPH)):
        raise HTTPException(401, "bad or missing signature")
    try:
        event = json.loads(body)
    except ValueError:
        raise HTTPException(400, "not JSON") from None
    if event.get("type") != "post_call_transcription":
        return {"ignored": event.get("type")}
    data = event.get("data") or {}
    call_id = data.get("conversation_id")
    variables = (data.get("conversation_initiation_client_data") or {}).get("dynamic_variables") or {}
    gap = next((g for g in GRAPH.gaps() if call_id and g.get("call_id") == call_id), None)
    # A call this server placed reached the owner's phone. The browser widget names its gap itself and
    # anyone can open it, so its answers are stored as unverified, not as a phone call with the owner.
    source = "voice_call"
    if gap is None:
        gap, source = GRAPH.gap(str(variables.get("gap_id", ""))), "voice_widget_unverified"
    if gap is None:
        return {"ignored": "no matching gap"}
    if gap["status"] == "answered":
        return {"ignored": "already answered"}
    extracted = voice.extract_answer(data.get("transcript") or [], gap["draft"])
    if extracted is None:
        return {"ignored": "nothing said"}
    answer, result = extracted
    stored = gaps.answer_gap(GRAPH, gap["id"], answer, source, f"call-{call_id or gap['id']}",
                             draft_result=result, call_id=call_id)
    return {"answered": stored["id"], "draft_result": stored["draft_result"]}
