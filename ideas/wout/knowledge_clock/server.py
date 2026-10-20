import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from knowledge_clock.clock import compute_topics, parse_at, summarize, topic_detail
from knowledge_clock.store import apply_whys, load_aliases, load_signals, load_whys, save_why

BASE = Path(__file__).resolve().parents[1]
DEMO_NOW = "2026-10-20T16:15:00+02:00"

app = FastAPI(title="Knowledge clock")


class WhyAnswer(BaseModel):
    id: str
    why: str = Field(max_length=200, pattern=r"\S")


def _whys_path() -> Path:
    return BASE / os.environ.get("KC_WHYS", "data/whys.json")


def _config() -> dict:
    now = os.environ.get("KC_NOW") or DEMO_NOW
    signals, skipped = load_signals([BASE / p.strip() for p in os.environ.get("KC_SIGNALS", "data/signals.json").split(",")])
    return {
        "signals": apply_whys(signals, load_whys(_whys_path())),
        "skipped": skipped,
        "aliases": load_aliases(BASE / os.environ.get("KC_ALIASES", "data/aliases.json")),
        "fading_days": int(os.environ.get("KC_FADING_DAYS", "14")),
        "now": datetime.now(timezone.utc) if now == "live" else parse_at(now),
    }


def _topics(cfg: dict) -> list[dict]:
    return compute_topics(cfg["signals"], cfg["now"], cfg["fading_days"], cfg["aliases"])


@app.get("/api/summary")
def get_summary() -> dict:
    cfg = _config()
    return {**summarize(_topics(cfg)), "skipped": cfg["skipped"], "now": cfg["now"].astimezone(timezone.utc).isoformat()}


@app.get("/api/topics")
def get_topics() -> list[dict]:
    return _topics(_config())


@app.get("/api/topics/{topic}")
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


@app.get("/api/questions")
def get_questions(person: str) -> list[dict]:
    return [
        {"id": s["id"], "topic": s["topic"], "at": s["at"], "human_role": s["human_role"]}
        for s in _config()["signals"]
        if s["person"] == person and _is_open_question(s)
    ]


@app.post("/api/why", status_code=204)
def post_why(answer: WhyAnswer) -> Response:
    # Only open questions, so nobody can overwrite a quote or put words on an AI-handled row.
    if not any(s["id"] == answer.id and _is_open_question(s) for s in _config()["signals"]):
        raise HTTPException(status_code=404, detail="No open question with this id")
    save_why(_whys_path(), answer.id, answer.why.strip())
    return Response(status_code=204)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(BASE / "knowledge_clock" / "static" / "index.html")
