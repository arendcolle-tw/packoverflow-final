import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from knowledge_clock.clock import compute_topics, parse_at, summarize, topic_detail
from knowledge_clock.store import load_aliases, load_signals

BASE = Path(__file__).resolve().parents[1]
DEMO_NOW = "2026-10-20T16:15:00+02:00"

app = FastAPI(title="Knowledge clock")


def _config() -> dict:
    now = os.environ.get("KC_NOW") or DEMO_NOW
    signals, skipped = load_signals([BASE / p.strip() for p in os.environ.get("KC_SIGNALS", "data/signals.json").split(",")])
    return {
        "signals": signals,
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


@app.get("/")
def index() -> FileResponse:
    return FileResponse(BASE / "knowledge_clock" / "static" / "index.html")
