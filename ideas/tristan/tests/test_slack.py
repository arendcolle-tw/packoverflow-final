import asyncio
import re

import pytest
from slack_bolt.async_app import AsyncApp
from slack_bolt.request.async_request import AsyncBoltRequest
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.web.async_slack_response import AsyncSlackResponse

import knowly.slack as slack

QUESTION = "What time does the nightly payroll export start?"
PAYROLL = {"person": "tristan", "task": "Payroll SFTP export", "at": "2026-10-19T15:00:00+00:00",
           "why": "Retry 3 times, not 5, \"because the bank closes the SFTP window at 18:00\"", "topic": "payroll"}
RECORD = {"id": "q1", "question": QUESTION, "asker": "lies", "target": "tristan", "related": [PAYROLL],
          "status": "open", "created_at": "2026-10-20T10:00:00+00:00"}


def texts(blocks):
    for block in blocks:
        if isinstance(block.get("text"), dict):
            yield block["text"]["text"]
        for element in block.get("elements", []):
            if element.get("type") == "mrkdwn":
                yield element["text"]


class FakeAsker:
    def __init__(self, result=None, fail=None):
        self.notify = None
        self.result = result or {"known": False, "text": "Not recorded yet.\n\nI asked tristan; ask again once they have answered.",
                                 "question_id": "q1", "pinged": "tristan", "sources": [PAYROLL]}
        self.fail = fail
        self.asked, self.answers, self.records = [], [], {"q1": dict(RECORD)}

    async def ask(self, question, asker):
        self.asked.append((question, asker))
        return self.result

    def record_answer(self, question_id, person, text):
        if self.fail:
            raise self.fail
        self.answers.append((question_id, person, text))
        return {"id": f"ask:{question_id}:{person}", "why": text}

    def get(self, question_id):
        return self.records.get(question_id)


class FakeClient(AsyncWebClient):
    calls: list = []
    members = [{"id": "UTRISTAN", "profile": {"real_name": "Tristan Verbeken"}},
               {"id": "UWOUT", "profile": {"real_name": "Wout Doe"}}]

    async def api_call(self, api_method, *, http_verb="POST", files=None, data=None, params=None, json=None,
                       headers=None, auth=None):
        args = {**(params or {}), **(data or {}), **(json or {})}
        self.calls.append((api_method, {k: v for k, v in args.items() if v is not None}))
        body = {
            "auth.test": {"user_id": "UBOT", "bot_id": "BBOT", "team_id": "T1"},
            "users.list": {"members": self.members},
            "conversations.open": {"channel": {"id": f"D{args.get('users')}"}},
            "chat.postMessage": {"channel": args.get("channel"), "ts": "2.0"},
        }.get(api_method, {})
        return AsyncSlackResponse(client=self, http_verb=http_verb, api_url=api_method, req_args={},
                                  data={"ok": True, **body}, headers={}, status_code=200)


@pytest.fixture
def fake_slack(monkeypatch):
    monkeypatch.setattr(slack, "_people_cache", {"at": 0.0, "ids": {}})
    monkeypatch.delenv("SLACK_PEOPLE", raising=False)
    # Bolt builds a new AsyncWebClient for every request, so the fake replaces the class.
    monkeypatch.setattr("slack_bolt.app.async_app.AsyncWebClient", FakeClient)
    monkeypatch.setattr(FakeClient, "calls", [])
    sent = []

    class FakeWebhook:
        def __init__(self, url, **_):
            pass

        async def send_dict(self, message):
            sent.append(message)

    monkeypatch.setattr("slack_bolt.context.respond.async_respond.AsyncWebhookClient", FakeWebhook)
    return FakeClient.calls, sent


def make_bot(asker):
    app = AsyncApp(token="xoxb-test", process_before_response=True)
    slack.register(app, asker)
    return app


def dispatch(app, body):
    return asyncio.run(app.async_dispatch(AsyncBoltRequest(body=body, mode="socket_mode")))


def event(kind, text, **extra):
    return {"type": "event_callback", "team_id": "T1", "api_app_id": "A1", "event_id": "Ev1", "event_time": 1,
            "event": {"type": kind, "user": "UWOUT", "channel": "C1", "ts": "1.0", "text": text, **extra}}


def submission(text, user="UTRISTAN", question_id="q1"):
    return {"type": "view_submission", "team": {"id": "T1"}, "user": {"id": user}, "api_app_id": "A1", "trigger_id": "t",
            "view": {"id": "V1", "type": "modal", "callback_id": "answer_question", "private_metadata": question_id,
                     "state": {"values": {"answer": {"text": {"type": "plain_text_input", "value": text}}}}}}


def posted(calls, method="chat.postMessage"):
    return [args for name, args in calls if name == method]


def test_register_sets_notify_and_attaches_the_listeners(fake_slack):
    asker = FakeAsker()
    app = make_bot(asker)
    assert asker.notify is not None
    assert {listener.ack_function.__name__ for listener in app._async_listeners} == {
        "on_mention", "on_dm", "on_command", "on_answer_button", "on_answer_submit"}


def test_mention_shows_looking_then_the_answer_with_sources_and_who_was_pinged(fake_slack):
    calls, _ = fake_slack
    asker = FakeAsker()
    response = dispatch(make_bot(asker), event("app_mention", f"<@UBOT> {QUESTION} <!channel>"))
    assert response.status == 200
    assert asker.asked == [(f"{QUESTION} !channel", "wout")]
    [looking] = posted(calls)
    assert looking == {"channel": "C1", "thread_ts": "1.0", "text": "Looking it up..."}
    [update] = posted(calls, "chat.update")
    assert update["channel"] == "C1" and update["ts"] == "2.0"
    text = "\n".join(texts(update["blocks"]))
    assert "I asked tristan" in text and "Related: Tristan in “Payroll SFTP export”, 19 Oct 2026" in text
    assert "Asked <@UTRISTAN> in a Slack DM" in text and "<!" not in text + update["text"]


def test_dm_answers_a_known_question_without_a_ping(fake_slack, monkeypatch):
    calls, _ = fake_slack
    monkeypatch.setenv("SLACK_PEOPLE", "lies:ULIES")
    asker = FakeAsker({"known": True, "text": "**Tristan** said it starts at 16:00 <b>", "question_id": None,
                       "pinged": None, "sources": [PAYROLL]})
    dispatch(make_bot(asker), event("message", QUESTION, channel_type="im", user="ULIES"))
    assert asker.asked == [(QUESTION, "lies")]
    assert "thread_ts" not in posted(calls)[0]
    [update] = posted(calls, "chat.update")
    text = "\n".join(texts(update["blocks"]))
    assert "*Tristan* said it starts at 16:00 &lt;b&gt;" in text and "From Tristan in" in text and "Asked" not in text


def test_dm_ignores_bot_messages_and_edits(fake_slack):
    calls, _ = fake_slack
    asker = FakeAsker()
    app = make_bot(asker)
    dispatch(app, event("message", QUESTION, channel_type="im", bot_id="B1"))
    dispatch(app, event("message", QUESTION, channel_type="im", subtype="message_changed"))
    assert asker.asked == [] and not posted(calls)


def test_unmapped_slack_user_asks_as_their_user_id_and_errors_show_in_the_reply(fake_slack):
    calls, _ = fake_slack

    class DownAsker(FakeAsker):
        async def ask(self, question, asker):
            self.asked.append((question, asker))
            raise ConnectionError("graph <down>")

    asker = DownAsker()
    dispatch(make_bot(asker), event("app_mention", "<@UBOT> payroll export", user="UNOBODY1"))
    assert asker.asked == [("payroll export", "UNOBODY1")]
    [update] = posted(calls, "chat.update")
    assert "Could not look that up: graph &lt;down&gt;" in update["blocks"][0]["text"]["text"]


def test_command_acks_looking_then_answers_in_channel(fake_slack):
    _, sent = fake_slack
    asker = FakeAsker()
    body = {"command": "/knowly", "text": QUESTION, "team_id": "T1", "user_id": "UTRISTAN", "channel_id": "C1",
            "response_url": "https://hooks.slack.test/x", "trigger_id": "t", "api_app_id": "A1"}
    response = dispatch(make_bot(asker), body)
    assert "Looking it up..." in response.body
    assert asker.asked == [(QUESTION, "tristan")]
    assert sent[0]["response_type"] == "in_channel" and sent[0]["blocks"][0]["text"]["text"] == f"*Knowly:* _{QUESTION}_"


def test_notify_dms_the_target_with_the_question_related_facts_and_an_answer_button(fake_slack):
    calls, _ = fake_slack
    asyncio.run(slack.notify_slack(FakeClient(token="xoxb-test"), {**RECORD, "question": "<!here> payroll & export"}))
    assert posted(calls, "conversations.open") == [{"users": "UTRISTAN"}]
    [dm] = posted(calls)
    assert dm["channel"] == "DUTRISTAN" and "&lt;!here&gt; payroll &amp; export" in dm["text"]
    text = "\n".join(texts(dm["blocks"]))
    assert "Lies asked: _&lt;!here&gt; payroll &amp; export_" in text and "bank closes the SFTP window at 18:00" in text
    assert "Tristan in “Payroll SFTP export”, 19 Oct 2026" in text
    [button] = dm["blocks"][-1]["elements"]
    assert (button["action_id"], button["value"], button["text"]["text"]) == ("answer_question", "q1", "Answer")


def test_notify_skips_a_target_without_a_slack_user(fake_slack):
    calls, _ = fake_slack
    asyncio.run(slack.notify_slack(FakeClient(token="xoxb-test"), {**RECORD, "target": "nobody"}))
    assert not posted(calls)


def test_answer_button_opens_a_modal_with_a_200_char_input(fake_slack):
    calls, sent = fake_slack
    app = make_bot(FakeAsker())
    body = {"type": "block_actions", "team": {"id": "T1"}, "user": {"id": "UTRISTAN"}, "api_app_id": "A1",
            "channel": {"id": "DUTRISTAN"}, "response_url": "https://hooks.slack.test/x", "trigger_id": "trig",
            "actions": [{"type": "button", "action_id": "answer_question", "block_id": "b", "value": "q1"}]}
    assert dispatch(app, body).status == 200
    [opened] = posted(calls, "views.open")
    view = opened["view"]
    assert opened["trigger_id"] == "trig" and view["callback_id"] == "answer_question" and view["private_metadata"] == "q1"
    element = view["blocks"][-1]["element"]
    assert element["multiline"] and element["max_length"] == 200 and len(view["title"]["text"]) <= 24
    assert QUESTION in view["blocks"][0]["text"]["text"]

    body["actions"][0]["value"] = "gone"
    dispatch(app, body)
    assert len(posted(calls, "views.open")) == 1 and sent[0]["response_type"] == "ephemeral"


def test_submit_stores_the_answer_closes_the_modal_and_dms_both_sides(fake_slack, monkeypatch):
    calls, _ = fake_slack
    monkeypatch.setenv("SLACK_PEOPLE", "lies:ULIES")
    asker = FakeAsker()
    answer = "It starts at 16:00 so three retries still finish before the bank's 18:00 cutoff"
    response = dispatch(make_bot(asker), submission(f"  {answer} "))
    assert response.status == 200 and response.body == ""
    assert asker.answers == [("q1", "tristan", answer)]
    to_tristan, to_lies = posted(calls)
    assert to_tristan["channel"] == "DUTRISTAN" and to_tristan["text"].startswith("Stored as your answer")
    assert to_lies["channel"] == "DULIES" and "<@UTRISTAN> answered your question" in to_lies["text"]
    assert "bank's 18:00 cutoff" in to_lies["text"]


def test_submit_skips_the_asker_dm_when_the_asker_is_not_in_slack(fake_slack):
    calls, _ = fake_slack
    asker = FakeAsker()
    dispatch(make_bot(asker), submission("16:00"))
    assert asker.answers == [("q1", "tristan", "16:00")]
    assert [m["channel"] for m in posted(calls)] == ["DUTRISTAN"]


@pytest.mark.parametrize("text, user, question_id, error", [
    ("   ", "UTRISTAN", "q1", "Type an answer first."),
    ("x" * 201, "UTRISTAN", "q1", "200 characters"),
    ("16:00", "UWOUT", "q1", "Only Tristan can answer"),
    ("16:00", "UNOBODY1", "q1", "SLACK_PEOPLE"),
    ("16:00", "UTRISTAN", "gone", "no longer exists"),
])
def test_submit_shows_errors_in_the_modal(fake_slack, text, user, question_id, error):
    calls, _ = fake_slack
    asker = FakeAsker()
    response = dispatch(make_bot(asker), submission(text, user, question_id))
    assert '"response_action": "errors"' in response.body and error in response.body
    assert asker.answers == [] and not posted(calls)


def test_submit_dms_the_error_when_the_graph_is_down(fake_slack):
    calls, _ = fake_slack
    asker = FakeAsker(fail=RuntimeError("graph <unreachable>"))
    response = dispatch(make_bot(asker), submission("16:00"))
    assert response.body == ""
    [dm] = posted(calls)
    assert dm["channel"] == "DUTRISTAN" and "Could not store your answer" in dm["text"]
    assert "graph &lt;unreachable&gt;" in dm["text"] and "Your answer was: 16:00" in dm["text"]


@pytest.mark.parametrize("filler", ["&" * 300, '"' * 300, "\x01" * 300, "\U0001f600" * 300])
def test_blocks_stay_within_block_kit_limits(filler):
    long = {"person": filler, "task": filler, "at": filler, "why": filler}
    result = {"known": False, "text": "\n".join([filler] * 20), "pinged": filler, "sources": [long] * 5}
    record = {**RECORD, "asker": filler, "question": filler, "related": [long] * 5}
    for blocks in (slack.answer_blocks(filler, result, {}), slack.question_blocks(record, {})):
        # Slack counts UTF-16 code units, two bytes each.
        assert all(0 < len(t.encode("utf-16-le")) <= 2 * 3000 for t in texts(blocks))
        assert len(blocks) <= 50


def test_fit_escapes_keeps_lines_and_never_splits_an_entity():
    assert slack.fit(" a  <b>\n\x01c & d ", 100) == "a &lt;b&gt;\nc &amp; d"
    assert slack.fit("ab&", 4) == "ab"


def test_plain_strips_slack_markup():
    text = "<@UBOT> who knows <!channel> &lt;deploy&gt; &amp; <https://x.io|the docs> in <#C1|ops>?"
    assert slack.plain(text) == "who knows !channel <deploy> & the docs in ops?"


def test_slack_people_skips_guests_display_names_and_shared_first_names(monkeypatch):
    monkeypatch.setattr(slack, "_people_cache", {"at": 0.0, "ids": {}})
    monkeypatch.setenv("SLACK_PEOPLE", "bob:UBOB, tristan:U0C9D2HJUA1")
    monkeypatch.setattr(FakeClient, "calls", [])
    monkeypatch.setattr(FakeClient, "members", [
        {"id": "UGUEST", "is_restricted": True, "profile": {"real_name": "Alice Outsider"}},
        {"id": "UEVE", "profile": {"real_name": "Eve Doe", "display_name": "Alice"}, "name": "alice"},
        {"id": "UALICE", "profile": {"real_name": "Alice Doe"}},
        {"id": "UBOB1", "profile": {"real_name": "Bob One"}},
        {"id": "UBOB2", "profile": {"real_name": "Bob Two"}},
        {"id": "UCAROL", "profile": {"real_name": "Carol Roe"}},
        {"id": "UCAROL2", "profile": {"real_name": "carol impostor"}},
        {"id": "UTRISTAN", "profile": {"real_name": "Tristan Verbeken"}},
    ])
    ids = asyncio.run(slack.slack_people(FakeClient(token="xoxb-test")))
    assert ids == {"alice": "UALICE", "eve": "UEVE", "bob": "UBOB", "tristan": "U0C9D2HJUA1"}
    assert slack.slack_id("tristan", ids) == "U0C9D2HJUA1" and slack.slack_id("U0C9D2HJUA1", {}) == "U0C9D2HJUA1"
    assert re.fullmatch(r"<@U0C9D2HJUA1>", slack.display("Tristan", ids)) and slack.display("lies", ids) == "Lies"
