import json
import logging
import os
import re
import time
import unicodedata
from datetime import datetime
from typing import Callable

from slack_bolt.async_app import AsyncApp
from slack_sdk.errors import SlackApiError

from whoknows.rank import parse_at, who_knows

STATUS = {
    "healthy": ":large_green_circle: *Healthy*: more than one person reasoned about this recently.",
    "single_point": ":large_orange_circle: *Single point*: only {owner} really knows this.",
    "fading": ":red_circle: *Fading*: nobody has reasoned about this in the last 30 days.",
    "dark": ":black_circle: *Dark*: Claude handled this every time. No human ever reasoned about it.",
    "unknown": ":white_circle: Nobody on the team has worked on this in a Claude session yet.",
}
ROLE_LABEL = {"decided": "decided", "corrected": "corrected Claude", "explained_why": "explained why"}
ESCAPE = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;"})
SLACK_MARKUP = re.compile(r"<@[A-Z0-9]+(?:\|[^<>]*)?>|<([^<>|]*)(?:\|([^<>]*))?>")
HELP = "Ask me about a task, for example `@whoknows set up the aikido security scan`."
_people_cache: dict = {"at": 0.0, "ids": {}}


def name_key(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return (ascii_name.lower().split() or [""])[0]


def oneline(text: str | None, limit: int) -> str:
    # Printable one-line text is at most 2 chars per char in JSON and 5 escaped, which keeps Block Kit limits.
    text = " ".join((text or "").split())
    return "".join(c for c in text if c.isprintable())[:limit]


def plain(text: str) -> str:
    """Slack message text as plain text: user mentions dropped, links and <!channel> reduced to their label."""
    text = SLACK_MARKUP.sub(lambda m: m.group(2) or m.group(1) or "", text)
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return oneline(text, 300)


async def slack_people(client) -> dict[str, str]:
    """Map person keys (first names) to Slack user ids. SLACK_PEOPLE=wout:U123,... overrides the lookup."""
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
            logging.getLogger(__name__).warning("users.list failed, answering without Ask buttons: %s", error)
    pairs = (pair.split(":", 1) for pair in os.environ.get("SLACK_PEOPLE", "").split(",") if ":" in pair)
    return {**_people_cache["ids"], **{name_key(name): user_id.strip() for name, user_id in pairs}}


def blocks(result: dict, slack_ids: dict[str, str]) -> list[dict]:
    names = {}
    for p in result["people"]:
        user_id = slack_ids.get(name_key(p["person"]))
        names[p["person"]] = f"<@{user_id}>" if user_id else oneline(p["person"].title(), 60).translate(ESCAPE)
    query = oneline(result["query"], 300)
    owner = names[result["knowers"][0]] if result["knowers"] else ""
    out = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Who knows:* _{query.translate(ESCAPE)}_"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": STATUS[result["status"]].format(owner=owner)}},
    ]
    top = result["people"][:2]
    for person in top:
        days = person["days_since"]
        roles = ", ".join(f"{n}× {ROLE_LABEL[r]}" for r, n in person["roles"].items() if r in ROLE_LABEL)
        lines = [f"*{names[person['person']]}* · last reasoned {'today' if days == 0 else f'{days} days ago'} · {roles}"]
        for evidence in person["evidence"][:1]:
            lines.append(f"> “{oneline(evidence['why'], 300).translate(ESCAPE)}”")
            lines.append(
                f"_Their own words, in the Claude session “{oneline(evidence['task'], 150).translate(ESCAPE)}” "
                f"on {parse_at(evidence['at']):%-d %b}._"
            )
        if not person["evidence"]:
            lines.append("_They decided or corrected Claude here, but never wrote down why._")
        out.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})
    out.append({"type": "context", "elements": [{"type": "mrkdwn", "text": (
        f"{result['similar_sessions']} similar Claude sessions · Claude alone {result['claude_alone']} · "
        f"human reasoning {result['human_reasoning']}. Only human reasoning counts as knowing."
    )}]})

    buttons = []
    for i, person in enumerate(top):
        user_id = slack_ids.get(name_key(person["person"]))
        if not user_id:
            continue
        evidence = (person["evidence"] or [{}])[0]
        value = {
            "user_id": user_id, "query": query[:200], "why": oneline(evidence.get("why"), 300),
            "task": oneline(evidence.get("task") or result["top_session"], 150),
        }
        buttons.append({
            "type": "button", "action_id": f"ask_person_{i}", "value": json.dumps(value, ensure_ascii=False),
            "text": {"type": "plain_text", "text": f"Ask {oneline(person['person'].title(), 60)}"},
        })
    if buttons:
        out.append({"type": "actions", "elements": buttons})
    return out


def register(app: AsyncApp, get_rows: Callable[[], list[dict]], now: datetime | None) -> None:
    async def answer(query: str, client) -> tuple[list[dict], str]:
        result = who_knows(query, get_rows(), now)
        return blocks(result, await slack_people(client)), f"Who knows: {query.translate(ESCAPE)}"

    @app.event("app_mention")
    async def on_mention(event, say, client):
        query = plain(event.get("text", ""))
        thread = event.get("thread_ts") or event["ts"]
        if len(query) < 2:
            await say(text=HELP, thread_ts=thread)
            return
        reply, text = await answer(query, client)
        await say(blocks=reply, text=text, thread_ts=thread)

    @app.event("message")
    async def on_dm(event, say, client):
        if event.get("channel_type") != "im" or event.get("bot_id") or event.get("subtype"):
            return
        query = plain(event.get("text", ""))
        if len(query) < 2:
            await say(text=HELP)
            return
        reply, text = await answer(query, client)
        await say(blocks=reply, text=text)

    @app.command("/whoknows")
    async def on_command(ack, command, respond, client):
        await ack()
        query = plain(command.get("text", ""))
        if len(query) < 2:
            await respond(text=HELP)
            return
        reply, text = await answer(query, client)
        await respond(blocks=reply, text=text, response_type="in_channel")

    @app.action(re.compile(r"^ask_person_\d+$"))
    async def on_ask(ack, body, action, client, respond):
        await ack()
        info = json.loads(action["value"])
        query, why, task = (str(info.get(k) or "").translate(ESCAPE) for k in ("query", "why", "task"))
        # A group DM with the asker gets the reply to them, and installs without mpim:write fall back to a 1:1 DM.
        try:
            dm = await client.conversations_open(users=",".join(dict.fromkeys([body["user"]["id"], info["user_id"]])))
        except SlackApiError:
            dm = await client.conversations_open(users=info["user_id"])
        reasoning = f"\n> “{why}”" if why else ""
        await client.chat_postMessage(channel=dm["channel"]["id"], text=(
            f"<@{body['user']['id']}> is working on “{query}”, and the team's Claude sessions point to you. "
            f"You reasoned about this in “{task}”:{reasoning}\nCan you help them?"
        ))
        await respond(text=f"Asked <@{info['user_id']}>, with your question and their earlier reasoning.",
                      response_type="ephemeral", replace_original=False)
