import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from knowly.ask import Asker
from knowly.graph import GraphClient, GraphError
from knowly.mcp_server import MemberMCP
from knowly.slack import register
from knowly.tokens import DEFAULT_DB, Tokens

DATA = Path(__file__).resolve().parents[2] / "data"
MAX_BODY = 4_000_000
PERSONAL_URL = re.compile(r"/u/[^/]+/")
tokens = Tokens(Path(os.environ.get("KNOWLY_TOKENS_DB", DEFAULT_DB)))
graph = GraphClient()
asker = Asker(graph, Path(os.environ.get("KNOWLY_QUESTIONS_DB", DATA / "questions.db")),
              Path(os.environ.get("KNOWLY_GRAPH_TOKENS", DATA / "graph_tokens.json")))
mcp = MemberMCP(tokens, asker)


def hide_token(record: logging.LogRecord) -> bool:
    # uvicorn's access log line holds the request path, and /u/<token>/mcp puts a member token in it.
    record.args = tuple(PERSONAL_URL.sub("/u/***/", a) if isinstance(a, str) else a for a in record.args or ())
    return True


logging.getLogger("uvicorn.access").addFilter(hide_token)


def member(authorization: str = Header("")) -> str:
    token = authorization.removeprefix("Bearer ").strip()
    person = tokens.person_for(token) if token else None
    if not person:
        raise HTTPException(401, "missing or unknown token")
    return person


@asynccontextmanager
async def lifespan(_: FastAPI):
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


app = FastAPI(title="Knowly", lifespan=lifespan)
app.add_route("/mcp", mcp, include_in_schema=False)
app.add_route("/u/{token}/mcp", mcp, include_in_schema=False)


@app.middleware("http")
async def limit_body(request: Request, call_next):
    # FastAPI reads and parses the body before the token check runs.
    if request.method == "POST" and int(request.headers.get("content-length") or MAX_BODY + 1) > MAX_BODY:
        return JSONResponse({"detail": "body too large or missing Content-Length"}, 413)
    return await call_next(request)


@app.post("/api/ask")
async def post_ask(question: str = Body(embed=True, min_length=2, max_length=300), person: str = Depends(member)) -> dict:
    try:
        return await asker.ask(question.strip(), person)
    except GraphError as error:
        raise HTTPException(502, f"knowledge graph unreachable: {error}") from error


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


def main() -> None:
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8091")))
