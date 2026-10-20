"""HTTP routes over the fact store. Reads are public; writes need a member token, new members the admin token.

Backtracking (gaps) env: ANTHROPIC_API_KEY, ELEVENLABS_*, KNOWLY_PHONE_NUMBERS.
"""

import hmac
import json
import os
import sys
import threading
import time
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from knowly.store import gaps, pages, voice
from knowly.store.facts import FactStore
from knowly.store.scoring import parse_at


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


class Draft(BaseModel):
    draft: str = Field(min_length=1, max_length=400, pattern=r"\S")
    check_question: str = Field(min_length=1, max_length=200, pattern=r"\S")


def _bearer(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    return token.strip()


def _at(at: str | None) -> datetime | None:
    try:
        return parse_at(at) if at else None
    except ValueError:
        raise HTTPException(422, "at is not an ISO time") from None


def _callable(owners: set[str]) -> set[str]:
    """Owners we can phone: calls configured and the owner opted in with a number in KNOWLY_PHONE_NUMBERS."""
    if not all(os.environ.get(k) for k in ("ELEVENLABS_PHONE_NUMBER_ID", "ELEVENLABS_API_KEY")):
        return set()
    return {o for o in owners if o and voice.phone_number(o)}


def build_router(store: FactStore, admin_token: str, public_url: str | None = None) -> APIRouter:
    """`public_url` is where this router is reachable from outside (e.g. https://host/store); without it the ElevenLabs
    post-call webhook is not registered."""
    gaps.find_gaps(store)
    if public_url:
        threading.Thread(target=voice.ensure_webhook, args=(store, public_url.rstrip("/") + "/webhooks/elevenlabs"),
                         daemon=True).start()
    threading.Thread(target=gaps.redraft_templates, args=(store,), daemon=True).start()
    last_redraft = [time.time()]
    router = APIRouter()

    def member(authorization: str | None = Header(None)) -> str:
        person = store.member(_bearer(authorization))
        if person is None:
            raise HTTPException(401, "unknown member token", headers={"WWW-Authenticate": "Bearer"})
        return person

    def admin(authorization: str | None = Header(None)) -> None:
        token = _bearer(authorization)
        if len(admin_token) < 32 or not hmac.compare_digest(token.encode(), admin_token.encode()):
            raise HTTPException(403, "admin token required")

    def gap_or_404(gap_id: str) -> dict:
        gap = store.gap(gap_id)
        if gap is None:
            raise HTTPException(404, "no such gap")
        return gap

    @router.post("/facts")
    def post_facts(rows: list[dict] = Body(..., max_length=1000), person: str = Depends(member)) -> dict:
        result = store.add_facts(rows, person=person)
        gaps.find_gaps(store)
        return result

    @router.post("/members", dependencies=[Depends(admin)])
    def post_members(body: NewMember) -> dict:
        person = body.person.strip()
        return {"person": person, "token": store.add_member(person)}

    @router.get("/who_knows")
    def get_who_knows(q: str = Query(..., min_length=1, max_length=300), at: str | None = None) -> dict:
        return store.who_knows(q, _at(at))

    @router.get("/people/{person}")
    def get_person(person: str, at: str | None = None) -> dict:
        return store.person_view(person, _at(at))

    @router.get("/risks")
    def get_risks(at: str | None = None) -> list[dict]:
        return store.risks(_at(at))

    @router.get("/rows")
    def get_rows() -> list[dict]:
        return store.rows()

    @router.get("/health")
    def health() -> dict:
        return {"storage": "gcs" if store.mirror else "local", "rows": len(store.rows())}

    # Backtracking: gaps, Claude's drafts, and the owner's answer. Drafts never enter /rows.

    @router.post("/artifacts", dependencies=[Depends(admin)])
    def post_artifacts(artifacts: list[Artifact] = Body(..., max_length=1000)) -> dict:
        for a in artifacts:
            _at(a.at)
        stored = store.add_artifacts([a.model_dump() for a in artifacts])
        return {"stored": stored, "open_gaps": len(gaps.find_gaps(store))}

    @router.get("/gaps")
    def get_gaps(status: str | None = None) -> list[dict]:
        """status=open means not answered yet (open, drafted or calling)."""
        found = gaps.all_gaps(store)
        if status == "open":
            found = [g for g in found if g["status"] in gaps.UNANSWERED]
        elif status:
            found = [g for g in found if g["status"] == status]
        return [gaps.public(g) for g in found]

    @router.post("/gaps/scan", dependencies=[Depends(admin)])
    def post_scan(claude: int = Query(0, ge=0, le=50)) -> dict:
        """Find gaps. With claude=N, also ask a model to draft the N riskiest that still have a template draft."""
        found = gaps.find_gaps(store)
        drafted = 0
        for gap in [g for g in found if g.get("draft_source") not in gaps.AI_SOURCES][:claude]:
            drafted += gaps.draft_gap(store, gap["id"])["draft_source"] in gaps.AI_SOURCES
        return {"open": len(found), "claude_drafts": drafted}

    @router.post("/gaps/{gap_id}/draft", dependencies=[Depends(admin)])
    def post_draft(gap_id: str, body: Draft | None = None) -> dict:
        """No body: ask a model (template fallback). With {draft, check_question}: store that draft as given."""
        gap_or_404(gap_id)
        if body is not None:
            return gaps.public(gaps.set_draft(store, gap_id, body.draft, body.check_question))
        return gaps.public(gaps.draft_gap(store, gap_id))

    @router.post("/gaps/{gap_id}/answer")
    def post_answer(gap_id: str, body: Answer, person: str = Depends(member)) -> dict:
        gap = gap_or_404(gap_id)
        if gap["owner"] != person:
            raise HTTPException(403, "only the owner can answer this gap")
        if gap["status"] == "answered":
            raise HTTPException(409, "already answered")
        return gaps.public(gaps.answer_gap(store, gap_id, body.answer, "gap_form", f"form-{gap_id}"))

    @router.get("/gaps/board", response_class=HTMLResponse)
    def get_board() -> str:
        # At most every 5 minutes, let a model replace a few template drafts in the background.
        if time.time() - last_redraft[0] > 300:
            last_redraft[0] = time.time()
            threading.Thread(target=gaps.redraft_templates, args=(store, 3), daemon=True).start()
        found = gaps.all_gaps(store)
        answered = sorted((g for g in found if g["status"] == "answered"), key=lambda g: g["answered_at"] or "", reverse=True)
        waiting = [g for g in found if g["status"] in gaps.UNANSWERED]
        return pages.board(waiting, answered, phone=_callable({g["owner"] for g in waiting}),
                           drafters={g.get("draft_source") for g in waiting} & gaps.AI_SOURCES)

    @router.get("/gaps/{gap_id}/talk", response_class=HTMLResponse)
    def get_talk(gap_id: str) -> str:
        gap = gap_or_404(gap_id)
        return pages.talk(gap, widget=voice.widget(gap) if gap["status"] != "answered" else "")

    @router.post("/gaps/{gap_id}/call", dependencies=[Depends(admin)])
    def post_call(gap_id: str, request: Request) -> dict:
        """Phone the owner. 409 with the talk page path when calls are not configured for them."""
        gap = gap_or_404(gap_id)
        if gap["status"] == "answered":
            raise HTTPException(409, "already answered")
        talk = request.url_for("get_talk", gap_id=gap_id).path
        try:
            call_id = voice.start_call(gap)
        except voice.NotConfigured as error:
            print(f"outbound call not configured: {error}", file=sys.stderr)
            raise HTTPException(409, f"Phone calls are not set up for this owner. Answer on the talk page: {talk}") from None
        except Exception as error:  # noqa: BLE001
            print(f"outbound call failed: {type(error).__name__}", file=sys.stderr)
            raise HTTPException(502, f"The call failed. Answer on the talk page: {talk}") from None
        gap.update(status="calling", call_id=call_id)
        store.save_gaps([gap])
        return gaps.public(gap)

    @router.post("/webhooks/elevenlabs")
    async def post_webhook(request: Request) -> dict:
        body = await request.body()
        if not voice.verify(request.headers.get("elevenlabs-signature"), body, voice.webhook_secret(store)):
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
        gap = next((g for g in store.gaps() if call_id and g.get("call_id") == call_id), None)
        # A call this server placed reached the owner's phone. The browser widget names its gap itself and
        # anyone can open it, so its answers are stored as unverified, not as a phone call with the owner.
        source = "voice_call"
        if gap is None:
            gap, source = store.gap(str(variables.get("gap_id", ""))), "voice_widget_unverified"
        if gap is None:
            return {"ignored": "no matching gap"}
        if gap["status"] == "answered":
            return {"ignored": "already answered"}
        extracted = voice.extract_answer(data.get("transcript") or [], gap["draft"])
        if extracted is None:
            return {"ignored": "nothing said"}
        answer, result = extracted
        stored = gaps.answer_gap(store, gap["id"], answer, source, f"call-{call_id or gap['id']}",
                                 draft_result=result, call_id=call_id)
        return {"answered": stored["id"], "draft_result": stored["draft_result"]}

    return router
