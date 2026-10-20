from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import unicodedata
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING

from slack_bolt.async_app import AsyncApp
from slack_sdk.errors import SlackApiError

if TYPE_CHECKING:
    from whoknows.ask import Asker

ESCAPE = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;"})
SLACK_MARKUP = re.compile(r"<@[A-Z0-9]+(?:\|[^<>]*)?>|<([^<>|]*)(?:\|([^<>]*))?>")
SLACK_ID = re.compile(r"[UW][A-Z0-9]{6,}")
HELP = "Ask me a question about the team's work, for example `@whoknows what time does the nightly payroll export start?`."
LOOKING = "Looking it up..."
log = logging.getLogger(__name__)
_people_cache: dict = {"at": 0.0, "ids": {}}


def name_key(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return (ascii_name.lower().split() or [""])[0]


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


async def slack_people(client) -> dict[str, str]:
    """Map person keys (first names) to Slack user ids. SLACK_PEOPLE=tristan:U123,... overrides the lookup."""
    if time.time() - _people_cache["at"] > 600:
        seen: dict[str, set[str]] = {}
        try:
            async for page in await client.users_list(limit=200):
                for member in page["members"]:
                    if member.get("deleted") or member.get("is_bot") or member.get("is_restricted") or member["id"] == "USLACKBOT":
                        continue
                    if key := name_key(member.get("profile", {}).get("real_name", "")):
                        seen.setdefault(key, set()).add(member["id"])
            # A first name shared by two members maps to nobody, so SLACK_PEOPLE has to name them.
            _people_cache.update(at=time.time(), ids={k: next(iter(v)) for k, v in seen.items() if len(v) == 1})
        except SlackApiError as error:
            log.warning("users.list failed, mapping people through SLACK_PEOPLE only: %s", error)
    pairs = (pair.split(":", 1) for pair in os.environ.get("SLACK_PEOPLE", "").split(",") if ":" in pair)
    return {**_people_cache["ids"], **{name_key(name): user_id.strip() for name, user_id in pairs}}


def slack_id(person: str | None, people: dict[str, str]) -> str | None:
    if SLACK_ID.fullmatch(person or ""):
        return person
    return people.get(name_key(person or ""))


def display(person: str | None, people: dict[str, str]) -> str:
    user_id = slack_id(person, people)
    return f"<@{user_id}>" if user_id else oneline((person or "someone").title(), 60).translate(ESCAPE)


def fact(source: dict) -> str:
    name = oneline((source.get("person") or "someone").title(), 60)
    return f"{name} in “{oneline(source.get('task') or source.get('source_id'), 150)}”, {day(source.get('at'))}"


def answer_blocks(question: str, result: dict, people: dict[str, str]) -> list[dict]:
    out = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Who knows:* _{oneline(question, 300).translate(ESCAPE)}_"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": fit((result.get("text") or "").replace("**", "*"), 3000) or "No answer."}},
    ]
    if sources := result.get("sources") or []:
        label = "From " if result.get("known") else "Related: "
        out.append({"type": "context", "elements": [
            {"type": "mrkdwn", "text": fit(label + " · ".join(fact(s) for s in sources[:3]), 3000)}]})
    if result.get("pinged"):
        out.append({"type": "context", "elements": [{"type": "mrkdwn", "text": (
            f":bell: Asked {display(result['pinged'], people)} in a Slack DM, with an Answer button.")}]})
    return out


def question_blocks(record: dict, people: dict[str, str]) -> list[dict]:
    out = [{"type": "section", "text": {"type": "mrkdwn", "text": (
        f":wave: {display(record['asker'], people)} asked: _{oneline(record['question'], 300).translate(ESCAPE)}_\n"
        "Nobody has recorded the answer yet. Your earlier work looks related:"
    )}}]
    for source in (record.get("related") or [])[:3]:
        out.append({"type": "section", "text": {"type": "mrkdwn", "text": (
            f"> “{oneline(source.get('why'), 300).translate(ESCAPE)}”\n_{fact(source).translate(ESCAPE)}_")}})
    out.append({"type": "actions", "elements": [{
        "type": "button", "action_id": "answer_question", "value": record["id"], "style": "primary",
        "text": {"type": "plain_text", "text": "Answer"},
    }]})
    return out


async def dm(client, user_id: str, **message) -> None:
    channel = (await client.conversations_open(users=user_id))["channel"]["id"]
    await client.chat_postMessage(channel=channel, **message)


async def notify_slack(client, record: dict) -> None:
    try:
        people = await slack_people(client)
        target = slack_id(record.get("target"), people)
        if not target:
            log.warning("no Slack user for %s, question %s waits in the store", record.get("target"), record["id"])
            return
        text = f"{oneline(record['asker'], 60)} asked: {oneline(record['question'], 300)}".translate(ESCAPE)
        await dm(client, target, text=text, blocks=question_blocks(record, people))
    except Exception:
        log.exception("could not DM %s about question %s", record.get("target"), record.get("id"))


def register(app: AsyncApp, asker: Asker) -> None:
    asker.notify = partial(notify_slack, app.client)

    async def answer(question: str, user_id: str, client) -> tuple[list[dict], str]:
        people = await slack_people(client)
        try:
            result = await asker.ask(question, asker={uid: name for name, uid in people.items()}.get(user_id, user_id))
        except Exception as error:
            log.exception("ask failed for %r", question)
            text = f":warning: Could not look that up: {fit(str(error), 1000)}"
            return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}], "Could not look that up"
        return answer_blocks(question, result, people), oneline(result.get("text"), 300).translate(ESCAPE) or LOOKING

    async def reply(question: str, user_id: str, say, client, **where) -> None:
        if len(question) < 2:
            await say(text=HELP, **where)
            return
        pending = await say(text=LOOKING, **where)
        blocks, text = await answer(question, user_id, client)
        await client.chat_update(channel=pending["channel"], ts=pending["ts"], blocks=blocks, text=text)

    @app.event("app_mention")
    async def on_mention(event, say, client):
        await reply(plain(event.get("text", "")), event.get("user", ""), say, client,
                    thread_ts=event.get("thread_ts") or event["ts"])

    @app.event("message")
    async def on_dm(event, say, client):
        if event.get("channel_type") != "im" or event.get("bot_id") or event.get("subtype"):
            return
        await reply(plain(event.get("text", "")), event.get("user", ""), say, client)

    @app.command("/whoknows")
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
                 "hint": {"type": "plain_text", "text": "Stored in the knowledge graph as your fact, at most 200 characters."},
                 "element": {"type": "plain_text_input", "action_id": "text", "multiline": True, "max_length": 200}},
            ],
        })

    @app.view("answer_question")
    async def on_answer_submit(ack, body, view, client):
        user_id = body["user"]["id"]
        text = ((view["state"]["values"].get("answer", {}).get("text") or {}).get("value") or "").strip()
        record = asker.get(view["private_metadata"])
        people = await slack_people(client)
        # Later entries are the SLACK_PEOPLE overrides, so they win over a users.list first name.
        person = {uid: name for name, uid in people.items()}.get(user_id)
        if not text:
            error = "Type an answer first."
        elif len(text) > 200:
            error = "Keep the answer to 200 characters."
        elif not record:
            error = "That question no longer exists."
        elif not person:
            error = "Your Slack account is not linked to a person in the knowledge graph. Add it to SLACK_PEOPLE."
        elif name_key(record["target"] or "") != person:
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
        await dm(client, user_id, text=f"Stored as your answer to “{question}”:\n> {fit(text, 1000)}")
        asker_id = slack_id(record["asker"], people)
        if asker_id and asker_id != user_id:
            await dm(client, asker_id, text=(
                f"{display(record['target'], people)} answered your question “{question}”:\n> {fit(text, 1000)}\n"
                "It is in the knowledge graph now, so asking again returns it."))
