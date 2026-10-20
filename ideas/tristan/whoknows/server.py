import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from whoknows.ask import Asker
from whoknows.graph import GraphClient, GraphError
from whoknows.mcp_server import MemberMCP
from whoknows.rank import parse_at, who_knows
from whoknows.slack import register
from whoknows.store import DEFAULT_DB, Store

DATA = Path(__file__).resolve().parent.parent / "data"
MAX_BODY = 4_000_000
PERSONAL_URL = re.compile(r"/u/[^/]+/")
FIXED_NOW = parse_at(os.environ["WHOKNOWS_NOW"]) if os.environ.get("WHOKNOWS_NOW") else None
store = Store(Path(os.environ.get("WHOKNOWS_DB", DEFAULT_DB)))
graph = GraphClient()
asker = Asker(graph, Path(os.environ.get("WHOKNOWS_QUESTIONS_DB", DATA / "questions.db")),
              Path(os.environ.get("WHOKNOWS_GRAPH_TOKENS", DATA / "graph_tokens.json")))
mcp = MemberMCP(store, asker)


def hide_token(record: logging.LogRecord) -> bool:
    # uvicorn's access log line holds the request path, and /u/<token>/mcp puts a member token in it.
    record.args = tuple(PERSONAL_URL.sub("/u/***/", a) if isinstance(a, str) else a for a in record.args or ())
    return True


logging.getLogger("uvicorn.access").addFilter(hide_token)


def member(authorization: str = Header("")) -> str:
    token = authorization.removeprefix("Bearer ").strip()
    person = store.person_for(token) if token else None
    if not person:
        raise HTTPException(401, "missing or unknown token")
    return person


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.seed(sorted(DATA.glob("signals-*.json")))
    handler = None
    if os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_APP_TOKEN"):
        bot = AsyncApp(token=os.environ["SLACK_BOT_TOKEN"])
        register(bot, asker)
        handler = AsyncSocketModeHandler(bot, os.environ["SLACK_APP_TOKEN"])
        # The SDK retries a failed connect forever, and uvicorn binds the port only after startup returns.
        connecting = asyncio.create_task(handler.connect_async())
    async with mcp.run():
        yield
    if handler:
        connecting.cancel()
        await handler.close_async()


app = FastAPI(title="Who knows", lifespan=lifespan)
app.add_route("/mcp", mcp, include_in_schema=False)
app.add_route("/u/{token}/mcp", mcp, include_in_schema=False)


@app.middleware("http")
async def limit_body(request: Request, call_next):
    # FastAPI reads and parses the body before the token check runs.
    if request.method == "POST" and int(request.headers.get("content-length") or MAX_BODY + 1) > MAX_BODY:
        return JSONResponse({"detail": "body too large or missing Content-Length"}, 413)
    return await call_next(request)


@app.post("/api/signals")
def post_signals(rows: list[dict] = Body(...), person: str = Depends(member)) -> dict:
    if len(rows) > 5000:
        raise HTTPException(413, "send at most 5000 rows per request")
    stored, skipped = store.upsert(rows, person)
    return {"stored": stored, "skipped": skipped}


@app.get("/api/who-knows")
def get_who_knows(q: str = Query(min_length=2, max_length=300), _: str = Depends(member)) -> dict:
    return who_knows(q, store.rows(), FIXED_NOW)


@app.post("/api/ask")
async def post_ask(question: str = Body(embed=True, min_length=2, max_length=300), person: str = Depends(member)) -> dict:
    try:
        return await asker.ask(question.strip(), person)
    except GraphError as error:
        raise HTTPException(502, f"knowledge graph unreachable: {error}") from error


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}
