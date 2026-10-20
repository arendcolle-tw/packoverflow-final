import asyncio
import logging
import re
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import uvicorn
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from knowly import config
from knowly.agent import answer
from knowly.ask import Asker
from knowly.client import StoreError
from knowly.mcp_server import MemberMCP
from knowly.members import Members
from knowly.slack.bot import register_bot
from knowly.slack.channel import register_channel
from knowly.slack.extract import extract
from knowly.store import build_router, open_store
from knowly.tokens import Tokens

MAX_BODY = 4_000_000
PERSONAL_URL = re.compile(r"/u/[^/]+/")


def hide_token(record: logging.LogRecord) -> bool:
    # uvicorn's access log line holds the request path, and /u/<token>/mcp puts a member token in it.
    record.args = tuple(PERSONAL_URL.sub("/u/***/", a) if isinstance(a, str) else a for a in record.args or ())
    return True


logging.getLogger("uvicorn.access").addFilter(hide_token)


def create_app(settings: config.Settings | None = None) -> FastAPI:
    settings = settings or config.load()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store_url = f"{settings.url}/store"
    store = open_store(settings.data_dir, settings.bucket)
    tokens = Tokens(settings.data_dir / "tokens.db")
    members = Members(store_url, settings.admin_token, settings.data_dir / "member_tokens.json")
    asker = Asker(store_url, settings.data_dir, members, default_expert=settings.default_expert)
    mcp = MemberMCP(tokens, asker)

    def member(authorization: str = Header("")) -> str:
        token = authorization.removeprefix("Bearer ").strip()
        person = tokens.person_for(token) if token else None
        if not person:
            raise HTTPException(401, "missing or unknown token")
        return person

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        handler = None
        if settings.slack_bot_token and settings.slack_app_token:
            bot = AsyncApp(token=settings.slack_bot_token)
            register_channel(bot, channel=settings.channel, answer_fn=answer, extract_fn=extract, members=members,
                             base_url=store_url, threads_db=settings.data_dir / "threads.db",
                             people=settings.people, allow_self=settings.allow_self)
            register_bot(bot, app.state.asker, settings)
            handler = AsyncSocketModeHandler(bot, settings.slack_app_token)
            # The SDK retries a failed connect forever, and uvicorn binds the port only after startup returns.
            connecting = asyncio.create_task(handler.connect_async())
        async with app.state.mcp.run():
            yield
        if handler:
            connecting.cancel()
            await handler.close_async()

    app = FastAPI(title="Knowly", lifespan=lifespan)
    app.state.settings, app.state.store, app.state.tokens = settings, store, tokens
    app.state.members, app.state.asker, app.state.mcp = members, asker, mcp
    # ElevenLabs can only call back a public URL, so a loopback KNOWLY_URL registers no voice webhook.
    public = urlsplit(settings.url).hostname not in ("127.0.0.1", "localhost", "::1")
    app.include_router(build_router(store, settings.admin_token, store_url if public else None), prefix="/store")
    app.add_route("/mcp", mcp, include_in_schema=False)
    app.add_route("/u/{token}/mcp", mcp, include_in_schema=False)

    @app.middleware("http")
    async def limit_body(request: Request, call_next):
        # FastAPI reads and parses the body before the token check runs.
        if request.method == "POST" and int(request.headers.get("content-length") or MAX_BODY + 1) > MAX_BODY:
            return JSONResponse({"detail": "body too large or missing Content-Length"}, 413)
        return await call_next(request)

    @app.post("/api/ask")
    async def post_ask(request: Request, question: str = Body(embed=True, min_length=2, max_length=300),
                       person: str = Depends(member)) -> dict:
        try:
            return await request.app.state.asker.ask(question.strip(), person)
        except StoreError as error:
            raise HTTPException(502, f"fact store unreachable: {error}") from error

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    return app


def main() -> None:
    settings = config.load()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
