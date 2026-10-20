"""Knowly in Slack DMs, @mentions outside the Knowly channel and /knowly, answered through the Asker."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING

from slack_bolt.async_app import AsyncApp
from slack_sdk.errors import SlackApiError

from knowly.agent import PING
from knowly.config import person_key
from knowly.slack.channel import channel_matcher, sources_block

if TYPE_CHECKING:
    from knowly.ask import Asker
    from knowly.config import Settings

ESCAPE = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;"})
SLACK_MARKUP = re.compile(r"<@[A-Z0-9]+(?:\|[^<>]*)?>|<([^<>|]*)(?:\|([^<>]*))?>")
SLACK_ID = re.compile(r"[UW][A-Z0-9]{6,}")
HELP = "Ask me a question about the team's work, for example `@knowly what time does the nightly payroll export start?`."
LOOKING = "Looking it up..."
log = logging.getLogger(__name__)
_people_cache: dict = {"at": 0.0, "ids": {}}


def oneline(text: str | None, limit: int) -> str:
    # Printable one-line text is at most 2 chars per char in JSON and 5 escaped, which keeps Block Kit limits.
    text = " ".join((text or "").split())
    return "".join(c for c in text if c.isprintable())[:limit]


def fit(text: str | None, limit: int) -> str:
    """Multi-line mrkdwn: escaped, printable, at most `limit` UTF-16 code units as Slack counts them."""
    out, size = [], 0
    for c in "\n".join(" ".join(line.split()) for line in (text or "").strip().splitlines()):
        if not (c.isprintable() or c == "\n"):
            continue
        piece = c.translate(ESCAPE)
        size += len(piece.encode("utf-16-le")) // 2
        if size > limit:
            break
        out.append(piece)
    return "".join(out)


def plain(text: str) -> str:
    """Slack message text as plain text: user mentions dropped, links and <!channel> reduced to their label."""
    text = SLACK_MARKUP.sub(lambda m: m.group(2) or m.group(1) or "", text)
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return oneline(text, 300)


def day(at: str | None) -> str:
    try:
        return f"{datetime.fromisoformat(at or ''):%-d %b %Y}"
    except ValueError:
        return oneline(at, 20)


async def slack_people(client, overrides: dict[str, str]) -> dict[str, str]:
    """Map person keys (first names) to Slack user ids. `overrides` (SLACK_PEOPLE) wins over the users.list lookup."""
    if time.time() - _people_cache["at"] > 600:
        seen: dict[str, set[str]] = {}
        try:
            async for page in await client.users_list(limit=200):
                for member in page["members"]:
                    if member.get("deleted") or member.get("is_bot") or member.get("is_restricted") or member["id"] == "USLACKBOT":
                        continue
                    if key := person_key(member.get("profile", {}).get("real_name", "")):
                        seen.setdefault(key, set()).add(member["id"])
            # A first name shared by two members maps to nobody, so SLACK_PEOPLE has to name them.
            _people_cache.update(at=time.time(), ids={k: next(iter(v)) for k, v in seen.items() if len(v) == 1})
        except SlackApiError as error:
            log.warning("users.list failed, mapping people through SLACK_PEOPLE only: %s", error)
    return {**_people_cache["ids"], **{person_key(name): user_id for name, user_id in overrides.items()}}


def slack_id(person: str | None, people: dict[str, str]) -> str | None:
    if SLACK_ID.fullmatch(person or ""):
        return person
    return people.get(person_key(person or ""))


def display(person: str | None, people: dict[str, str]) -> str:
    user_id = slack_id(person, people)
    return f"<@{user_id}>" if user_id else oneline((person or "someone").title(), 60).translate(ESCAPE)


def ping_text(record: dict, people: dict[str, str]) -> str:
    ping = record.get("ping") or PING.format(person="{person}", asker=(record.get("asker") or "someone").title(),
                                             question=record.get("question") or "")
    return fit(ping, 1300).replace("{person}", display(record.get("pinged") or record.get("target"), people))


def answer_blocks(result: dict, people: dict[str, str]) -> list[dict]:
    text = fit((result.get("answer") or result.get("text") or "").replace("**", "*"), 1300)
    if result.get("pinged"):
        text += "\n\n" + ping_text(result, people)
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}, *sources_block(result.get("sources") or [])]


def question_blocks(record: dict, people: dict[str, str]) -> list[dict]:
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": ping_text(record, people)}},
        *sources_block(record.get("related") or []),
        {"type": "actions", "elements": [{
            "type": "button", "action_id": "answer_question", "value": record["id"], "style": "primary",
            "text": {"type": "plain_text", "text": "Answer"},
        }]},
    ]


async def dm(client, user_id: str, **message) -> None:
    channel = (await client.conversations_open(users=user_id))["channel"]["id"]
    await client.chat_postMessage(channel=channel, **message)


async def notify_slack(client, overrides: dict[str, str], record: dict) -> None:
    try:
        people = await slack_people(client, overrides)
        target = slack_id(record.get("target"), people)
        if not target:
            log.warning("no Slack user for %s, question %s waits in the store", record.get("target"), record["id"])
            return
        await dm(client, target, text=ping_text(record, {}), blocks=question_blocks(record, people))
    except Exception:
        log.exception("could not DM %s about question %s", record.get("target"), record.get("id"))


async def in_dm(event: dict) -> bool:
    return event.get("channel_type") == "im"


def register_bot(app: AsyncApp, asker: Asker, settings: Settings) -> None:
    overrides = settings.people
    asker.notify = partial(notify_slack, app.client, overrides)
    in_knowly_channel = channel_matcher(settings.channel)

    async def answer(question: str, user_id: str, client) -> tuple[list[dict], str]:
        people = await slack_people(client, overrides)
        try:
            result = await asker.ask(question, asker={uid: name for name, uid in people.items()}.get(user_id, user_id))
        except Exception as error:
            log.exception("ask failed for %r", question)
            text = f":warning: Could not look that up: {fit(str(error), 1000)}"
            return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}], "Could not look that up"
        return answer_blocks(result, people), oneline(result.get("text"), 300).translate(ESCAPE) or LOOKING

    async def reply(question: str, user_id: str, say, client, **where) -> None:
        if len(question) < 2:
            await say(text=HELP, **where)
            return
        pending = await say(text=LOOKING, **where)
        blocks, text = await answer(question, user_id, client)
        await client.chat_update(channel=pending["channel"], ts=pending["ts"], blocks=blocks, text=text)

    @app.event("app_mention")
    async def on_mention(event, say, client):
        # The channel listener answers every message in the Knowly channel, mentions included.
        if await in_knowly_channel(event, client):
            return
        await reply(plain(event.get("text", "")), event.get("user", ""), say, client,
                    thread_ts=event.get("thread_ts") or event["ts"])

    # Bolt runs only the first matching listener, so this one must not match channel messages.
    @app.event("message", matchers=[in_dm])
    async def on_dm(event, say, client):
        if event.get("bot_id") or event.get("subtype"):
            return
        await reply(plain(event.get("text", "")), event.get("user", ""), say, client)

    @app.command("/knowly")
    async def on_command(ack, command, respond, client):
        question = plain(command.get("text", ""))
        if len(question) < 2:
            await ack(text=HELP)
            return
        await ack(text=LOOKING)
        blocks, text = await answer(question, command["user_id"], client)
        await respond(blocks=blocks, text=text, response_type="in_channel")

    @app.action("answer_question")
    async def on_answer_button(ack, body, action, client, respond):
        await ack()
        record = asker.get(action["value"])
        if not record:
            await respond(text="That question no longer exists.", response_type="ephemeral", replace_original=False)
            return
        question = oneline(record["question"], 300).translate(ESCAPE)
        await client.views_open(trigger_id=body["trigger_id"], view={
            "type": "modal", "callback_id": "answer_question", "private_metadata": record["id"],
            "title": {"type": "plain_text", "text": "Answer the question"},
            "submit": {"type": "plain_text", "text": "Store answer"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": f"{display(record['asker'], {})} asked: _{question}_"}},
                {"type": "input", "block_id": "answer", "label": {"type": "plain_text", "text": "Your answer"},
                 "hint": {"type": "plain_text", "text": "Stored in Knowly as your fact, at most 200 characters."},
                 "element": {"type": "plain_text_input", "action_id": "text", "multiline": True, "max_length": 200}},
            ],
        })

    @app.view("answer_question")
    async def on_answer_submit(ack, body, view, client):
        user_id = body["user"]["id"]
        text = ((view["state"]["values"].get("answer", {}).get("text") or {}).get("value") or "").strip()
        record = asker.get(view["private_metadata"])
        people = await slack_people(client, overrides)
        # Later entries are the SLACK_PEOPLE overrides, so they win over a users.list first name.
        person = {uid: name for name, uid in people.items()}.get(user_id)
        if not text:
            error = "Type an answer first."
        elif len(text) > 200:
            error = "Keep the answer to 200 characters."
        elif not record:
            error = "That question no longer exists."
        elif not person:
            error = "Your Slack account is not linked to a Knowly person. Add it to SLACK_PEOPLE."
        elif person_key(record["target"] or "") != person:
            error = f"Only {oneline(record['target'], 60).title()} can answer this question."
        else:
            error = None
        if error:
            await ack(response_action="errors", errors={"answer": error})
            return
        await ack()
        question = oneline(record["question"], 300).translate(ESCAPE)
        try:
            await asyncio.to_thread(asker.record_answer, record["id"], record["target"], text)
        except Exception as failure:
            log.exception("could not store the answer to question %s", record["id"])
            await dm(client, user_id, text=(
                f":warning: Could not store your answer to “{question}”: {fit(str(failure), 500)}\n"
                f"Your answer was: {fit(text, 1000)}"))
            return
        await dm(client, user_id, text=f"Thanks {display(record['target'], people)}, that's saved to Knowly now.")
        asker_id = slack_id(record["asker"], people)
        if asker_id and asker_id != user_id:
            await dm(client, asker_id, text=(
                f"{display(record['target'], people)} answered “{question}”: {fit(text, 1000)}\nIt's saved to Knowly now."))
