"""The #ask-knowly channel: Knowly answers each question in its thread, or tags the person most likely to know and
stores their thread reply as a fact under their name."""

import asyncio
import functools
import html
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from slack_bolt.async_app import AsyncApp
from slack_sdk.errors import SlackApiError

from knowly.agent import NO_ANSWER, PING
from knowly.config import person_key

log = logging.getLogger(__name__)

SCHEMA = """CREATE TABLE IF NOT EXISTS threads (
    thread_ts TEXT PRIMARY KEY, channel TEXT NOT NULL, question TEXT NOT NULL, asker TEXT NOT NULL,
    target TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, answered_at TEXT)"""
HUMAN_SUBTYPES = {None, "file_share", "thread_broadcast"}
TEXT_LIMIT = 3000
SOURCES_LIMIT = 10
LOOKING = "Looking it up..."

esc = functools.partial(html.escape, quote=False)


@contextmanager
def connect(path: Path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def plain(text: str) -> str:
    text = re.sub(r"<[@!][^>]*>", " ", text)
    text = re.sub(r"<[^>|]+\|([^>]+)>", r"\1", text)
    text = re.sub(r"<([^>]+)>", r"\1", text)
    return html.unescape(" ".join(text.split()))


def clip(text: str, limit: int = TEXT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return re.sub(r"&[a-z]*$", "", text[: limit - 1]) + "…"


def user_key(user: dict) -> str:
    real = user.get("real_name") or user.get("profile", {}).get("real_name") or user.get("name") or ""
    return person_key(real) or user["id"]


def day(at: str | None) -> str:
    try:
        moment = datetime.fromisoformat(at)
    except (TypeError, ValueError):
        return at or ""
    return f"{moment.day} {moment:%b %Y}"


def sources_block(sources: list[dict]) -> list[dict]:
    """One small context block, a "Person · date" line per distinct source."""
    lines = []
    for source in sources[:SOURCES_LIMIT]:
        # Capped parts keep ten escaped lines inside Slack's 3000-character text limit.
        line = " · ".join(part for part in (str(source.get("person") or "").title()[:40], day(source.get("at"))[:20]) if part)
        if line and line not in lines:
            lines.append(line)
    return [{"type": "context", "elements": [{"type": "mrkdwn", "text": clip(esc("\n".join(lines)))}]}] if lines else []


def answer_blocks(result: dict) -> list[dict]:
    answer = re.sub(r"\*\*(.+?)\*\*", r"*\1*", esc(result["answer"].strip()))
    return [{"type": "section", "text": {"type": "mrkdwn", "text": clip(answer)}}, *sources_block(result.get("sources") or [])]


def channel_matcher(channel: str):
    """A Bolt matcher that is true for events in `channel`, given as a channel id or a name with or without #."""
    channel = channel.lstrip("#")
    names: dict[str, str] = {}

    async def in_channel(event: dict, client) -> bool:
        channel_id = event.get("channel")
        if channel_id == channel:
            return True
        # app_mention events carry no channel_type and only happen in channels.
        if event.get("channel_type", "channel") not in ("channel", "group"):
            return False
        if channel_id not in names:
            try:
                names[channel_id] = (await client.conversations_info(channel=channel_id))["channel"].get("name", "")
            except SlackApiError:
                log.exception("conversations.info failed for %s", channel_id)
                names[channel_id] = ""
        return names[channel_id] == channel

    return in_channel


def register_channel(app: AsyncApp, *, channel: str, answer_fn: Callable[[str, str, str], dict],
                     extract_fn: Callable[[str, str, str], dict], members, base_url: str, threads_db: Path,
                     people: dict[str, str] | None = None, allow_self: bool = False) -> None:
    threads_db = Path(threads_db)
    threads_db.parent.mkdir(parents=True, exist_ok=True)
    with connect(threads_db) as db:
        db.execute(SCHEMA)
    ids: dict[str, str | None] = {person_key(person): user_id for person, user_id in (people or {}).items()}
    names = {user_id: person for person, user_id in ids.items()}
    seen: set[tuple[str, str]] = set()

    async def person_of(client, user_id: str) -> str:
        if user_id not in names:
            names[user_id] = user_key((await client.users_info(user=user_id))["user"])
            ids.setdefault(names[user_id], user_id)
        return names[user_id]

    async def slack_id(client, person: str) -> str | None:
        person = person_key(person)
        if person not in ids:
            try:
                async for page in await client.users_list(limit=200):
                    for user in page["members"]:
                        if not user.get("deleted") and not user.get("is_bot"):
                            names.setdefault(user["id"], user_key(user))
                            ids.setdefault(names[user["id"]], user["id"])
            except SlackApiError:
                log.exception("users.list failed, %s stays untagged", person)
            ids.setdefault(person, None)
        return ids[person]

    async def ask(event: dict, question: str, client) -> None:
        where = {"channel": event["channel"], "thread_ts": event["ts"]}
        asker = await person_of(client, event["user"])
        placeholder = await client.chat_postMessage(**where, text=LOOKING)
        try:
            result = await asyncio.to_thread(answer_fn, question, asker, base_url)
        except Exception:
            log.exception("answer_fn failed for %r", question)
            result = {}
        known = bool(result.get("answered") and (result.get("answer") or "").strip())
        if not (result.get("answer") or "").strip():
            result = {"answered": False, "answer": f"{NO_ANSWER}.", "sources": [], "ask_person": result.get("ask_person")}
        target = None if known else result.get("ask_person")
        await client.chat_update(channel=event["channel"], ts=placeholder["ts"], text=clip(esc(result["answer"].strip())),
                                 blocks=answer_blocks(result))
        with connect(threads_db) as db:
            db.execute("INSERT OR REPLACE INTO threads (thread_ts, channel, question, asker, target, status, created_at)"
                       " VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (event["ts"], event["channel"], question, asker, target, "known" if known else "open",
                        datetime.now(timezone.utc).isoformat(timespec="seconds")))
        if not target:
            return
        # A new message, because Slack does not notify people mentioned in an edit.
        user_id = await slack_id(client, target)
        who = f"<@{user_id}>" if user_id else f"*{esc(target.title())}*"
        ping = result.get("ping") or PING.format(person="{person}", asker=asker.title(), question=question)
        await client.chat_postMessage(**where, text=clip(esc(ping).replace("{person}", who)))

    async def reply(event: dict, text: str, thread_ts: str, client) -> None:
        with connect(threads_db) as db:
            thread = db.execute("SELECT * FROM threads WHERE thread_ts = ? AND channel = ? AND status = 'open'",
                                (thread_ts, event["channel"])).fetchone()
        if thread is None:
            return
        replier = await person_of(client, event["user"])
        target, asker = person_key(thread["target"] or "") or None, person_key(thread["asker"])
        if not (replier == target or (target is None and replier != asker) or (allow_self and replier == asker)):
            return
        extracted = await asyncio.to_thread(extract_fn, thread["question"], text, replier)
        if not extracted.get("is_answer"):
            return
        with connect(threads_db) as db:
            claimed = db.execute("UPDATE threads SET status = 'answered', answered_at = ? WHERE thread_ts = ? AND status = 'open'",
                                 (datetime.now(timezone.utc).isoformat(timespec="seconds"), thread_ts)).rowcount
        if not claimed:
            return
        where = {"channel": event["channel"], "thread_ts": thread_ts}
        try:
            await asyncio.to_thread(members.store_fact, replier, thread["question"], extracted["fact"],
                                    extracted["topic"], thread_ts)
        except Exception:
            log.exception("store_fact failed for thread %s", thread_ts)
            with connect(threads_db) as db:
                db.execute("UPDATE threads SET status = 'open', answered_at = NULL WHERE thread_ts = ?", (thread_ts,))
            await client.chat_postMessage(**where, text="I could not save that to Knowly. Reply again in a moment.")
            return
        await client.reactions_add(channel=event["channel"], timestamp=event["ts"], name="white_check_mark")
        await client.chat_postMessage(**where, text=f"Thanks <@{event['user']}>, that's saved to Knowly now.")

    @app.event("message", matchers=[channel_matcher(channel)])
    async def on_ask_knowly_message(event: dict, client) -> None:
        if event.get("bot_id") or event.get("subtype") not in HUMAN_SUBTYPES or not event.get("user"):
            return
        if (event["channel"], event["ts"]) in seen:
            return
        seen.add((event["channel"], event["ts"]))
        text = plain(event.get("text") or "")
        if not text:
            return
        thread_ts = event.get("thread_ts", event["ts"])
        if thread_ts == event["ts"]:
            await ask(event, text, client)
        else:
            await reply(event, text, thread_ts, client)
