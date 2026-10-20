import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
from slack_bolt.async_app import AsyncApp
from slack_bolt.request.async_request import AsyncBoltRequest
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.web.async_slack_response import AsyncSlackResponse

from knowly.slack.bot import register_bot
from knowly.slack.channel import register_channel

BASE = "http://knowly.test/store"
QUESTION = "When does the nightly payroll export start?"
PAYROLL = {"person": "tristan", "task": "Payroll SFTP export", "at": "2026-10-19T15:00:00+00:00",
           "why": "Retry 3 times, \"because the bank closes the SFTP window at 18:00\" <b>"}
RELATED = [PAYROLL] + [{"person": "sam", "task": f"Task {n}", "at": f"2026-10-1{n}T09:00:00+00:00", "why": f"why {n}"}
                       for n in range(1, 4)]
KNOWN = {"answered": True, "answer": "**Tristan** says it starts at 16:00 <b>", "sources": [PAYROLL],
         "ask_person": None, "why_them": None}
GAP_ANSWER = ("Based on what's in Knowly there's no answer to this yet. Tristan set up the payroll SFTP export, "
              "so he's the one to ask.")
GAP = {"answered": False, "answer": GAP_ANSWER, "sources": RELATED, "ask_person": "tristan",
       "why_them": "Tristan set up the payroll SFTP export", "ping": "{person}, do you know when the export starts?"}
FACT = {"is_answer": True, "fact": "It starts at 16:00, after the bank batch", "topic": "payroll-export"}
REAL_NAMES = {"ULIES": "Alberic Peeters", "UTRISTAN": "Tristan Verbeken", "USAM": "Sam Doe", "UALB": "Albéric Dupont"}
CHANNELS = {"CASK": "ask-knowly", "COTHER": "random"}


class FakeClient(AsyncWebClient):
    calls: list = []

    async def api_call(self, api_method, *, http_verb="POST", files=None, data=None, params=None, json=None,
                       headers=None, auth=None):
        args = {**(params or {}), **(data or {}), **(json or {})}
        self.calls.append((api_method, {k: v for k, v in args.items() if v is not None}))
        body = {
            "auth.test": {"user_id": "UBOT", "bot_id": "BBOT", "team_id": "T1"},
            "users.info": {"user": {"id": args.get("user"), "real_name": REAL_NAMES.get(args.get("user"), "")}},
            "users.list": {"members": [{"id": uid, "real_name": name} for uid, name in REAL_NAMES.items()]
                           + [{"id": "UBOTUSER", "real_name": "Tristan Bot", "is_bot": True}]},
            "conversations.info": {"channel": {"id": args.get("channel"), "name": CHANNELS.get(args.get("channel"))}},
            "chat.postMessage": {"channel": args.get("channel"), "ts": f"9.{len(self.calls)}"},
        }.get(api_method, {})
        return AsyncSlackResponse(client=self, http_verb=http_verb, api_url=api_method, req_args={"params": params or {}},
                                  data={"ok": True, **body}, headers={}, status_code=200)


class FakeMembers:
    def __init__(self, fail=None):
        self.stored, self.fail = [], fail

    def store_fact(self, person, question, fact, topic, question_id):
        if self.fail:
            raise self.fail
        self.stored.append((person, question, fact, topic, question_id))
        return {"id": f"thread:{question_id}:{person}"}


class Bot:
    def __init__(self, tmp_path, answer=KNOWN, extract=FACT, members=None, app=None, **options):
        self.answer, self.extract = answer, extract
        self.asked, self.extracted = [], []
        self.members = members or FakeMembers()
        self.db = tmp_path / "threads.db"
        self.app = app or AsyncApp(token="xoxb-test", process_before_response=True)
        options.setdefault("channel", "ask-knowly")
        register_channel(self.app, answer_fn=self.answer_fn, extract_fn=self.extract_fn, members=self.members,
                         base_url=BASE, threads_db=self.db, **options)

    def answer_fn(self, question, asker, base_url):
        self.asked.append((question, asker, base_url))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    def extract_fn(self, question, reply, replier):
        self.extracted.append((question, reply, replier))
        return self.extract

    def run(self, *bodies):
        async def dispatch_all():
            return [(await self.app.async_dispatch(AsyncBoltRequest(body=body, mode="socket_mode"))).status
                    for body in bodies]
        return asyncio.run(dispatch_all())

    def thread(self, ts="100.0"):
        with sqlite3.connect(self.db) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM threads WHERE thread_ts = ?", (ts,)).fetchone()
        return dict(row) if row else None


@pytest.fixture
def calls(monkeypatch):
    # Bolt builds a new AsyncWebClient for every request, so the fake replaces the class.
    monkeypatch.setattr("slack_bolt.app.async_app.AsyncWebClient", FakeClient)
    monkeypatch.setattr(FakeClient, "calls", [])
    return FakeClient.calls


def message(text, user="ULIES", ts="100.0", channel="CASK", **extra):
    return {"type": "event_callback", "team_id": "T1", "api_app_id": "A1", "event_id": f"Ev{ts}{user}", "event_time": 1,
            "event": {"type": "message", "channel_type": "channel", "user": user, "channel": channel, "ts": ts,
                      "text": text, **extra}}


def reply(text, user="UTRISTAN", ts="101.0", **extra):
    return message(text, user=user, ts=ts, thread_ts="100.0", **extra)


def posted(calls, method="chat.postMessage"):
    return [args for name, args in calls if name == method]


def slack_calls(calls):
    return [name for name, _ in calls if name not in ("auth.test", "users.info", "users.list", "conversations.info")]


def block_text(blocks):
    return "\n".join(block["text"]["text"] if block["type"] == "section" else block["elements"][0]["text"]
                     for block in blocks)


def test_known_question_updates_the_placeholder_with_the_answer_and_sources(tmp_path, calls):
    bot = Bot(tmp_path)
    assert bot.run(message(f"<@UBOT> {QUESTION} &amp; <!channel> <https://wiki.example/payroll|the wiki>")) == [200]
    assert bot.asked == [(f"{QUESTION} & the wiki", "alberic", BASE)]
    [placeholder] = posted(calls)
    assert placeholder == {"channel": "CASK", "thread_ts": "100.0", "text": "Looking it up..."}
    [update] = posted(calls, "chat.update")
    assert update["channel"] == "CASK" and update["ts"].startswith("9.")
    assert update["text"] == "**Tristan** says it starts at 16:00 &lt;b&gt;"
    assert block_text(update["blocks"]) == "*Tristan* says it starts at 16:00 &lt;b&gt;\nTristan · 19 Oct 2026"
    assert slack_calls(calls) == ["chat.postMessage", "chat.update"]
    assert bot.thread() | {"created_at": None} == {
        "thread_ts": "100.0", "channel": "CASK", "question": f"{QUESTION} & the wiki", "asker": "alberic", "target": None,
        "status": "known", "created_at": None, "answered_at": None}


def test_unknown_question_posts_the_agent_text_and_pings_the_target_in_a_new_message(tmp_path, calls):
    bot = Bot(tmp_path, answer=GAP)
    bot.run(message(QUESTION))
    [update] = posted(calls, "chat.update")
    assert update["text"] == GAP_ANSWER
    assert block_text(update["blocks"]) == (
        f"{GAP_ANSWER}\nTristan · 19 Oct 2026\nSam · 11 Oct 2026\nSam · 12 Oct 2026\nSam · 13 Oct 2026")
    [_, ping] = posted(calls)
    assert ping == {"channel": "CASK", "thread_ts": "100.0", "text": "<@UTRISTAN>, do you know when the export starts?"}
    assert bot.thread()["status"] == "open" and bot.thread()["target"] == "tristan"


def test_reply_by_the_target_is_extracted_stored_confirmed_and_closes_the_thread(tmp_path, calls):
    bot = Bot(tmp_path, answer=GAP)
    bot.run(message(QUESTION), reply("It starts at 16:00, after the bank batch &lt;3"))
    assert bot.extracted == [(QUESTION, "It starts at 16:00, after the bank batch <3", "tristan")]
    assert bot.members.stored == [("tristan", QUESTION, FACT["fact"], "payroll-export", "100.0")]
    assert posted(calls, "reactions.add") == [{"channel": "CASK", "timestamp": "101.0", "name": "white_check_mark"}]
    confirmation = posted(calls)[-1]
    assert confirmation["thread_ts"] == "100.0"
    assert confirmation["text"] == "Thanks <@UTRISTAN>, that's saved to Knowly now."
    thread = bot.thread()
    assert thread["status"] == "answered" and thread["answered_at"]


def test_replies_from_others_and_after_the_answer_are_ignored(tmp_path, calls):
    bot = Bot(tmp_path, answer=GAP)
    bot.run(message(QUESTION), reply("I think it is 17:00 honestly", user="USAM"),
            reply("Me too, wondering the same thing", user="ULIES", ts="102.0"))
    assert bot.extracted == [] and bot.thread()["status"] == "open"
    bot.run(reply("It starts at 16:00, after the bank batch", ts="103.0"),
            reply("Actually it starts at 16:30 now", ts="104.0"))
    assert len(bot.extracted) == 1 and len(bot.members.stored) == 1
    assert len(posted(calls, "reactions.add")) == 1


def test_non_answer_reply_does_nothing_and_keeps_the_thread_open(tmp_path, calls):
    bot = Bot(tmp_path, answer=GAP, extract={"is_answer": False, "fact": "", "topic": ""})
    bot.run(message(QUESTION))
    before = list(calls)
    bot.run(reply("let me check"))
    assert bot.extracted == [(QUESTION, "let me check", "tristan")]
    assert bot.members.stored == [] and calls[len(before):] == []
    assert bot.thread()["status"] == "open"


def test_bot_edited_deleted_and_other_channel_messages_are_ignored(tmp_path, calls):
    bot = Bot(tmp_path)
    bot.run(message(QUESTION, bot_id="BOTHER"),
            message(QUESTION, ts="200.0", subtype="bot_message", user=None),
            message(QUESTION, ts="201.0", subtype="message_changed"),
            message(QUESTION, ts="202.0", subtype="message_deleted"),
            message(QUESTION, ts="203.0", channel="COTHER"),
            message(QUESTION, ts="204.0", channel="DLIES", channel_type="im"),
            message("   ", ts="205.0"),
            reply("A reply in a thread Knowly never opened", ts="206.0"))
    assert bot.asked == [] and slack_calls(calls) == []


def test_duplicate_delivery_is_handled_once(tmp_path, calls):
    bot = Bot(tmp_path)
    bot.run(message(QUESTION), message(QUESTION))
    assert len(bot.asked) == 1 and slack_calls(calls) == ["chat.postMessage", "chat.update"]


def test_without_a_target_anyone_but_the_asker_may_answer_unless_allow_self(tmp_path, calls):
    nobody = {**GAP, "ask_person": None, "why_them": None}
    bot = Bot(tmp_path / "strict", answer=nobody)
    bot.run(message(QUESTION), reply("It starts at 16:00, after the bank batch", user="ULIES"))
    assert len(posted(calls)) == 1 and bot.extracted == []
    bot.run(reply("It starts at 16:00, after the bank batch", user="USAM", ts="102.0"))
    assert [stored[0] for stored in bot.members.stored] == ["sam"]

    solo = Bot(tmp_path / "solo", answer=nobody, allow_self=True)
    solo.run(message(QUESTION), reply("It starts at 16:00, after the bank batch", user="ULIES"))
    assert [stored[0] for stored in solo.members.stored] == ["alberic"]


def test_allow_self_lets_the_asker_answer_a_tagged_thread(tmp_path, calls):
    bot = Bot(tmp_path, answer=GAP, allow_self=True)
    bot.run(message(QUESTION), reply("It starts at 16:00, after the bank batch", user="ULIES"))
    assert [stored[0] for stored in bot.members.stored] == ["alberic"]
    assert posted(calls)[-1]["text"] == "Thanks <@ULIES>, that's saved to Knowly now."


def test_people_override_maps_both_ways_and_untagged_targets_are_named(tmp_path, calls):
    bot = Bot(tmp_path, answer={**GAP, "ask_person": "noor"}, people={"noor": "UNOOR", "alberic": "ULIESALT"})
    bot.run(message(QUESTION, user="ULIESALT"), reply("It starts at 16:00, after the bank batch", user="UNOOR"))
    assert bot.asked[0][1] == "alberic"
    assert posted(calls)[1]["text"].startswith("<@UNOOR>, do you know")
    assert [stored[0] for stored in bot.members.stored] == ["noor"]
    assert not [args for name, args in calls if name == "users.info"]

    calls.clear()
    stranger = Bot(tmp_path / "stranger", answer={**GAP, "ask_person": "zoë"})
    stranger.run(message(QUESTION))
    assert posted(calls)[-1]["text"].startswith("*Zoë*, do you know")


def test_answer_failure_says_there_is_no_answer_and_leaves_the_thread_open(tmp_path, calls):
    bot = Bot(tmp_path, answer=RuntimeError("claude down"))
    bot.run(message(QUESTION))
    assert posted(calls, "chat.update")[0]["text"] == "Based on what's in Knowly there's no answer to this yet."
    assert len(posted(calls)) == 1 and bot.thread()["status"] == "open"


def test_ping_without_agent_text_uses_the_fallback_sentence(tmp_path, calls):
    bot = Bot(tmp_path, answer={**GAP, "ping": None})
    bot.run(message(QUESTION))
    assert posted(calls)[-1]["text"] == f"<@UTRISTAN>, Alberic is asking: “{QUESTION}” Do you know?"


def test_accented_names_map_to_plain_person_keys(tmp_path, calls):
    bot = Bot(tmp_path, answer={**GAP, "ask_person": "Albéric"}, people={"TRISTAN": "UTRISTAN"})
    bot.run(message(QUESTION, user="UALB"))
    assert bot.asked[0][1] == "alberic" and bot.thread()["asker"] == "alberic"
    assert posted(calls)[-1]["text"].startswith("<@UALB>, do you know")
    solo = Bot(tmp_path / "solo", answer=GAP, allow_self=True, people={"Albéric": "UALB"})
    solo.run(message(QUESTION, user="UALB"), reply("It starts at 16:00, after the bank batch", user="UALB"))
    assert [stored[0] for stored in solo.members.stored] == ["alberic"]


def test_store_failure_reports_and_reopens_the_thread(tmp_path, calls):
    bot = Bot(tmp_path, answer=GAP, members=FakeMembers(fail=RuntimeError("rejected")))
    bot.run(message(QUESTION), reply("It starts at 16:00, after the bank batch"))
    assert posted(calls)[-1]["text"] == "I could not save that to Knowly. Reply again in a moment."
    assert posted(calls, "reactions.add") == [] and bot.thread()["status"] == "open"


def test_channel_by_id_and_other_message_listeners_still_get_their_events(tmp_path, calls):
    bot = Bot(tmp_path, channel="CASK")
    dms = []

    @bot.app.event("message")
    async def on_dm(event):
        dms.append(event["text"])

    bot.run(message(QUESTION), message("hello", ts="300.0", channel="DLIES", channel_type="im"))
    assert len(bot.asked) == 1 and dms == ["hello"]
    assert not [name for name, _ in calls if name == "conversations.info"]


def test_the_bot_registered_first_leaves_channel_messages_to_the_channel_listener(tmp_path, calls):
    class Asker:
        notify = None

    app = AsyncApp(token="xoxb-test", process_before_response=True)
    register_bot(app, Asker(), SimpleNamespace(people={}, channel="ask-knowly"))
    bot = Bot(tmp_path, app=app)
    bot.run(message(QUESTION))
    assert len(bot.asked) == 1 and slack_calls(calls) == ["chat.postMessage", "chat.update"]
