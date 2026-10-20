import hashlib
import hmac
import json
import time

import pytest

from knowly.store import gaps, voice
from knowly.store.scoring import row_weight

SECRET = "whsec_test"


@pytest.fixture(autouse=True)
def voice_env(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("KNOWLY_PHONE_NUMBERS", '{"alberic": "+32470000001", "jan": "+32470000002"}')
    for key in ("K_SERVICE", "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID", "ELEVENLABS_PHONE_NUMBER_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(gaps, "ask_json", lambda *a, **k: None)
    monkeypatch.setattr(voice, "ask_json", lambda *a, **k: None)
    monkeypatch.setattr(voice.httpx, "post", lambda *a, **k: pytest.fail("network call in a test"))


def signed(body: dict, secret=SECRET, stamp=None):
    raw = json.dumps(body).encode()
    stamp = stamp or int(time.time())
    sig = hmac.new(secret.encode(), f"{stamp}.".encode() + raw, hashlib.sha256).hexdigest()
    return {"content": raw, "headers": {"ElevenLabs-Signature": f"t={stamp},v0={sig}", "Content-Type": "application/json"}}


def event(gap, user_lines, conversation_id="conv1"):
    transcript = [{"role": "agent", "message": f"Claude guessed: {gap['draft']} Is that right?"}]
    transcript += [{"role": "user", "message": line} for line in user_lines]
    return {"type": "post_call_transcription", "data": {
        "conversation_id": conversation_id, "transcript": transcript,
        "conversation_initiation_client_data": {"dynamic_variables": voice.dynamic_variables(gap)}}}


def lies_gap(client):
    return next(g for g in client.get("/gaps", params={"status": "open"}).json() if g["owner"] == "alberic")


def test_unsigned_or_badly_signed_webhooks_are_refused(client, demo):
    body = event(lies_gap(client), ["We did it because the jury reads the repo."])
    assert client.post("/webhooks/elevenlabs", json=body).status_code == 401
    assert client.post("/webhooks/elevenlabs", **signed(body, secret="wrong")).status_code == 401
    assert client.post("/webhooks/elevenlabs", **signed(body, stamp=int(time.time()) - 7200)).status_code == 401
    assert client.get("/gaps", params={"status": "answered"}).json() == []


def test_webhook_stores_confirmed_at_half_and_edited_at_full_weight(client, demo):
    found = [g for g in client.get("/gaps", params={"status": "open"}).json() if g["owner"] == "alberic"]
    first, second = found[0], found[1]

    result = client.post("/webhooks/elevenlabs", **signed(event(first, ["Yes.", "Yes, that's right."], "c1"))).json()
    assert result["draft_result"] == "confirmed"
    second_words = second["draft"].split(" because")[0] + " because the scan blocked our deploy at 18:00 on the night before."
    result = client.post("/webhooks/elevenlabs", **signed(event(second, [second_words, "Yes."], "c2"))).json()
    assert result["draft_result"] in ("edited", "rewritten")

    rows = {r["id"]: r for r in client.get("/rows").json()}
    confirmed, edited = rows[f"gap-{first['id']}"], rows[f"gap-{second['id']}"]
    # No call was placed by the server here, so these came through the browser widget.
    assert confirmed["source"] == "voice_widget_unverified" and confirmed["source_id"] == "call-c1" and confirmed["draft"] == "confirmed"
    assert row_weight(confirmed) == 0.5 and row_weight(edited) == 1.0
    assert edited["why"] == second_words[:200] and edited["person"] == "alberic"
    assert client.post("/webhooks/elevenlabs", **signed(event(second, ["again"], "c2"))).json() == {"ignored": "already answered"}


def test_extract_keeps_only_near_verbatim_spans(monkeypatch):
    transcript = [{"role": "agent", "message": "Is that right?"},
                  {"role": "user", "message": "No, we retry three times because the SFTP window closes at six."}]
    monkeypatch.setattr(voice, "ask_json", lambda *a, **k: {"answer": "Because the bank's API rate limits us.", "just_confirmed": False})
    answer, _ = voice.extract_answer(transcript, "draft")
    assert answer == transcript[1]["message"]  # Claude's invented span is dropped
    monkeypatch.setattr(voice, "ask_json", lambda *a, **k: {"answer": "we retry three times because the SFTP window closes at six", "just_confirmed": False})
    assert voice.extract_answer(transcript, "draft")[0] == "we retry three times because the SFTP window closes at six"


def test_call_needs_admin_and_falls_back_when_not_configured(client, demo, admin):
    gap = lies_gap(client)
    assert client.post(f"/gaps/{gap['id']}/call").status_code == 401
    response = client.post(f"/gaps/{gap['id']}/call", headers=admin)
    assert response.status_code == 409 and f"/store/gaps/{gap['id']}/talk" in response.json()["detail"]


def test_call_starts_and_never_returns_the_number(client, demo, admin, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "agent_1")
    monkeypatch.setenv("ELEVENLABS_PHONE_NUMBER_ID", "phnum_1")
    sent = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"success": True, "message": "ok", "conversation_id": "conv9", "callSid": "CA1"}

    def fake_post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(voice.httpx, "post", fake_post)
    gap = lies_gap(client)
    response = client.post(f"/gaps/{gap['id']}/call", headers=admin)
    assert response.status_code == 200 and response.json()["status"] == "calling" and response.json()["call_id"] == "conv9"
    assert sent["url"].endswith("/v1/convai/twilio/outbound-call") and sent["json"]["to_number"] == "+32470000001"
    assert sent["json"]["conversation_initiation_client_data"]["dynamic_variables"]["gap_id"] == gap["id"]
    assert "data-call" in client.get("/gaps/board").text

    pages = [response.text] + [client.get(p).text for p in ("/gaps", "/gaps/board", "/rows", f"/gaps/{gap['id']}/talk")]
    assert not any("+3247" in p for p in pages)

    result = client.post("/webhooks/elevenlabs", **signed({"type": "post_call_transcription", "data": {
        "conversation_id": "conv9", "transcript": [{"role": "user", "message": "We picked it because the jury checks it."}]}})).json()
    assert result["answered"] == gap["id"]


def test_talk_page_has_the_widget_for_the_agent(client, demo, monkeypatch):
    gap = lies_gap(client)
    assert voice.AGENT_ID in client.get(f"/gaps/{gap['id']}/talk").text
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "agent_1")
    page = client.get(f"/gaps/{gap['id']}/talk").text
    assert "<elevenlabs-convai" in page and "agent_1" in page and gap["id"] in page


def test_store_registers_its_own_webhook_and_keeps_the_secret(client, demo, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_WEBHOOK_SECRET")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    calls = []

    class Response:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self.body

    def fake(method):
        def call(url, **kwargs):
            calls.append((method, url, kwargs.get("json")))
            return Response({"webhook_id": "wh1", "webhook_secret": "wsec_from_api"})
        return call

    monkeypatch.setattr(voice.httpx, "post", fake("post"))
    monkeypatch.setattr(voice.httpx, "patch", fake("patch"))
    voice.ensure_webhook(demo, "https://knowly.example/store/webhooks/elevenlabs")
    voice.ensure_webhook(demo, "https://knowly.example/store/webhooks/elevenlabs")  # already has a secret: no second webhook
    assert [c[0] for c in calls] == ["post", "patch"]
    assert calls[0][2]["settings"]["webhook_url"] == "https://knowly.example/store/webhooks/elevenlabs"
    assert calls[1][1].endswith(voice.AGENT_ID)
    assert calls[1][2]["platform_settings"]["workspace_overrides"]["webhooks"]["post_call_webhook_id"] == "wh1"

    gap = lies_gap(client)
    body = event(gap, ["We did it because the jury reads the repo."])
    assert client.post("/webhooks/elevenlabs", **signed(body, secret="wsec_from_api")).status_code == 200
    pages = [client.get(p).text for p in ("/gaps", "/gaps/board", "/rows", "/health", f"/gaps/{gap['id']}/talk")]
    assert not any("wsec_from_api" in p for p in pages)
