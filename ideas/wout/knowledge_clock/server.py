import logging
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from knowledge_clock.clock import compute_topics, parse_at, summarize, topic_detail
from knowledge_clock.connector import PersonGate, build_mcp
from knowledge_clock.live_store import LiveStore
from knowledge_clock.people import person_key
from knowledge_clock.store import apply_whys, load_aliases, load_signals, load_whys, save_why
from vendor.knowledge_graph import KnowledgeGraph

BASE = Path(__file__).resolve().parents[1]
STATIC = BASE / "knowledge_clock" / "static"
DEMO_NOW = "2026-10-20T16:15:00+02:00"
# Cloud Run sets K_SERVICE: use real time and its writable /tmp there.
ON_CLOUD_RUN = "K_SERVICE" in os.environ
CLAUDE_INSTALL = "https://claude.ai/customize/connectors?modal=add-custom-connector&connectorName=Packoverflow&connectorUrl="


class WhyAnswer(BaseModel):
    id: str
    why: str = Field(max_length=200, pattern=r"\S")


class JoinRequest(BaseModel):
    name: str = Field(max_length=100)


def _whys_path() -> Path:
    return BASE / os.environ.get("KC_WHYS", "data/whys.json")


def _data_dir() -> Path:
    return Path(os.environ.get("KC_DATA_DIR") or ("/tmp/kc" if ON_CLOUD_RUN else BASE / "data/live"))


def _make_mirror() -> tuple[object | None, str]:
    if not ON_CLOUD_RUN:
        return None, "local"
    try:
        from knowledge_clock.gcs_mirror import GcsMirror

        mirror = GcsMirror(os.environ.get("KC_BUCKET"))
        mirror.download_all(_data_dir())
        return mirror, "gcs"
    except Exception as error:  # noqa: BLE001
        return None, f"local ({type(error).__name__})"


MIRROR, STORAGE = _make_mirror()

PERSONAL_URL = re.compile(r"/u/[^/]+/")


def hide_token(record: logging.LogRecord) -> bool:
    # The access log line holds the request path, and /u/<token>/mcp puts a member token in it.
    record.args = tuple(PERSONAL_URL.sub("/u/***/", a) if isinstance(a, str) else a for a in record.args or ())
    return True


logging.getLogger("uvicorn.access").addFilter(hide_token)


def _seeds() -> list[Path]:
    return [BASE / p.strip() for p in os.environ.get("KC_SIGNALS", "data/signals.json").split(",") if p.strip()]


def _person_aliases() -> dict[str, str]:
    return load_aliases(BASE / os.environ.get("KC_PERSON_ALIASES", "data/person_aliases.json"))


def _store() -> LiveStore:
    return LiveStore([], _data_dir(), mirror=MIRROR, person_aliases=_person_aliases())


def _graph() -> KnowledgeGraph:
    # Albéric's graph is the single source of truth; the connector and the page only read it.
    return KnowledgeGraph(_data_dir() / "graph.jsonl", seed_paths=[s for s in _seeds() if s.exists()], mirror=MIRROR)


def _now() -> datetime:
    now = os.environ.get("KC_NOW") or ("live" if ON_CLOUD_RUN else DEMO_NOW)
    return datetime.now(timezone.utc) if now == "live" else parse_at(now)


def _config() -> dict:
    return {
        "signals": apply_whys(_graph().rows(), load_whys(_whys_path())),
        "skipped": load_signals(_seeds())[1],
        "aliases": load_aliases(BASE / os.environ.get("KC_ALIASES", "data/aliases.json")),
        "fading_days": int(os.environ.get("KC_FADING_DAYS", "14")),
        "now": _now(),
    }


router = APIRouter()


def _topics(cfg: dict) -> list[dict]:
    return compute_topics(cfg["signals"], cfg["now"], cfg["fading_days"], cfg["aliases"])


@router.get("/api/summary")
def get_summary() -> dict:
    cfg = _config()
    return {
        **summarize(_topics(cfg)),
        "skipped": cfg["skipped"],
        "now": cfg["now"].astimezone(timezone.utc).isoformat(),
        "storage": STORAGE,
    }


@router.get("/api/topics")
def get_topics() -> list[dict]:
    return _topics(_config())


@router.get("/api/topics/{topic}")
def get_topic(topic: str) -> dict:
    cfg = _config()
    detail = topic_detail(cfg["signals"], topic, cfg["now"], cfg["fading_days"], cfg["aliases"])
    if detail is None:
        raise HTTPException(status_code=404, detail="Unknown topic")
    return detail


def _is_open_question(signal: dict) -> bool:
    return (
        signal["human_role"] in {"decided", "corrected"} and signal["source"] == "claude_session"
        and signal["actor"] == "human" and signal["why"] is None
    )


@router.get("/api/questions")
def get_questions(person: str) -> list[dict]:
    return [
        {"id": s["id"], "topic": s["topic"], "at": s["at"], "human_role": s["human_role"]}
        for s in _config()["signals"]
        if s["person"] == person and _is_open_question(s)
    ]


@router.post("/api/why", status_code=204)
def post_why(answer: WhyAnswer, authorization: str = Header("")) -> Response:
    # The person comes from their member token, so nobody can put words in someone else's mouth.
    person = _store().person_for(authorization.removeprefix("Bearer ").strip())
    if person is None:
        raise HTTPException(status_code=401, detail="Join first: your member token is required")
    # Only open questions, so nobody can overwrite a quote or put words on an AI-handled row.
    if not any(s["id"] == answer.id and s["person"] == person and _is_open_question(s) for s in _config()["signals"]):
        raise HTTPException(status_code=404, detail="No open question with this id")
    save_why(_whys_path(), answer.id, answer.why.strip())
    return Response(status_code=204)


def _base(request: Request) -> str:
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{scheme}://{request.headers.get('host', request.url.netloc)}"


def _links(url: str) -> dict:
    return {
        "url": url,
        "claude_ai": f"{CLAUDE_INSTALL}{quote(url, safe='')}",
        "claude_code": f"claude mcp add --transport http packoverflow {url}",
    }


@router.get("/api/connector")
def connector(request: Request) -> dict:
    return _links(f"{_base(request)}/mcp")


_JOINS: dict[str, list[float]] = {}


def _join_allowed(ip: str, limit: int = 5, window: float = 600) -> bool:
    now = time.monotonic()
    recent = [t for t in _JOINS.get(ip, []) if now - t < window]
    if len(recent) >= limit:
        return False
    _JOINS[ip] = recent + [now]
    if len(_JOINS) > 5000:
        _JOINS.clear()
    return True


@router.post("/api/join")
def join(body: JoinRequest, request: Request) -> dict:
    if not _join_allowed(request.headers.get("x-forwarded-for", "").split(",")[-1].strip() or str(request.client and request.client.host)):
        raise HTTPException(status_code=429, detail="Too many joins, try again in a few minutes")
    store = _store()
    person = person_key(body.name)
    # One connector per name: a second join under a taken name would let anyone act as that person.
    if person and store.has_member(store.person_aliases.get(person, person)):
        raise HTTPException(status_code=409, detail="This name already has a connector")
    member = store.create_member(body.name)
    if member is None:
        raise HTTPException(status_code=422, detail="Name must be 1 to 40 characters")
    token, person = member
    return {"person": person, **_links(f"{_base(request)}/u/{token}/mcp")}


# The pages change during the day; a cached copy calls an API shape that no longer exists.
NO_STORE = {"Cache-Control": "no-store"}


@router.get("/join")
def join_page() -> FileResponse:
    return FileResponse(STATIC / "join.html", headers=NO_STORE)


@router.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers=NO_STORE)


def create_app() -> FastAPI:
    # The MCP session manager runs once per instance, so every app gets its own.
    mcp = build_mcp(_graph, _now, _person_aliases)
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="Knowledge clock", lifespan=lifespan)
    app.mount("/u/{token}", PersonGate(mcp_app, _store))
    app.include_router(router)
    # Last, so it only catches /mcp: the shared, read-only connector that needs no name.
    app.mount("/", mcp_app)
    return app


app = create_app()
