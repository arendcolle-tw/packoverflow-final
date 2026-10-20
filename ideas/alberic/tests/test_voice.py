import hashlib
import hmac
import importlib
import json
import time

import pytest
from fastapi.testclient import TestClient

from knowledge_graph import gaps, voice
from proficiency.score import row_weight

ADMIN = "a" * 40
SECRET = "whsec_test"
NUMBERS = '{"wout": "+32470000001", "arend": "+32470000002"}'


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KG_ADMIN_TOKEN", ADMIN)
    monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("KG_PHONE_NUMBERS", NUMBERS)
    for key in ("K_SERVICE", "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID", "ELEVENLABS_PHONE_NUMBER_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(gaps, "ask_json", lambda *a, **k: None)
    monkeypatch.setattr(voice, "ask_json", lambda *a, **k: None)
    monkeypatch.setattr(voice.httpx, "post", lambda *a, **k: pytest.fail("network call in a test"))
    import knowledge_graph.server as server

    return importlib.reload(server)


@pytest.fixture
def client(server):
    return TestClient(server.app)


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


def wout_gap(client):
    return next(g for g in client.get("/gaps", params={"status": "open"}).json() if g["owner"] == "wout")


def test_unsigned_or_badly_signed_webhooks_are_refused(client):
    gap = wout_gap(client)
    body = event(gap, ["We did it because the jury reads the repo."])
    assert client.post("/webhooks/elevenlabs", json=body).status_code == 401
    assert client.post("/webhooks/elevenlabs", **signed(body, secret="wrong")).status_code == 401
    assert client.post("/webhooks/elevenlabs", **signed(body, stamp=int(time.time()) - 7200)).status_code == 401
    assert client.get("/gaps", params={"status": "answered"}).json() == []


def test_webhook_stores_confirmed_at_half_and_edited_at_full_weight(client):
    found = [g for g in client.get("/gaps", params={"status": "open"}).json() if g["owner"] == "wout"]
    first, second = found[0], found[1]

    result = client.post("/webhooks/elevenlabs", **signed(event(first, ["Yes.", "Yes, that's right."], "c1"))).json()
    assert result["draft_result"] == "confirmed"
    second_words = second["draft"].replace("Was that because ...?", "because the scan blocked our deploy at 18:00.")
    result = client.post("/webhooks/elevenlabs", **signed(event(second, [second_words, "Yes."], "c2"))).json()
    assert result["draft_result"] in ("edited", "rewritten")

    rows = {r["id"]: r for r in client.get("/rows").json()}
    confirmed, edited = rows[f"gap-{first['id']}"], rows[f"gap-{second['id']}"]
    assert confirmed["source"] == "voice_call" and confirmed["source_id"] == "call-c1" and confirmed["draft"] == "confirmed"
    assert row_weight(confirmed) == 0.5 and row_weight(edited) == 1.0
    assert edited["why"] == second_words[:200] and edited["person"] == "wout"
    assert client.post("/webhooks/elevenlabs", **signed(event(second, ["again"], "c2"))).json() == {"ignored": "already answered"}


def test_extract_keeps_only_near_verbatim_spans(monkeypatch):
    transcript = [{"role": "agent", "message": "Is that right?"},
                  {"role": "user", "message": "No, we retry three times because the SFTP window closes at six."}]
    monkeypatch.setattr(voice, "ask_json", lambda *a, **k: {"answer": "Because the bank's API rate limits us.", "just_confirmed": False})
    answer, _ = voice.extract_answer(transcript, "draft")
    assert answer == transcript[1]["message"]  # Claude's invented span is dropped
    monkeypatch.setattr(voice, "ask_json", lambda *a, **k: {"answer": "we retry three times because the SFTP window closes at six", "just_confirmed": False})
    assert voice.extract_answer(transcript, "draft")[0] == "we retry three times because the SFTP window closes at six"


def test_call_needs_admin_and_falls_back_when_not_configured(client):
    gap = wout_gap(client)
    assert client.post(f"/gaps/{gap['id']}/call").status_code == 401
    response = client.post(f"/gaps/{gap['id']}/call", headers={"Authorization": f"Bearer {ADMIN}"})
    assert response.status_code == 409 and "/talk" in response.json()["detail"]


def test_call_starts_and_never_returns_the_number(client, monkeypatch):
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
    gap = wout_gap(client)
    response = client.post(f"/gaps/{gap['id']}/call", headers={"Authorization": f"Bearer {ADMIN}"})
    assert response.status_code == 200 and response.json()["status"] == "calling" and response.json()["call_id"] == "conv9"
    assert sent["url"].endswith("/v1/convai/twilio/outbound-call") and sent["json"]["to_number"] == "+32470000001"
    assert sent["json"]["conversation_initiation_client_data"]["dynamic_variables"]["gap_id"] == gap["id"]
    assert "data-call" in client.get("/gaps/board").text

    pages = [response.text] + [client.get(p).text for p in ("/gaps", "/gaps/board", "/rows", f"/gaps/{gap['id']}/talk")]
    assert not any("+3247" in p for p in pages)

    result = client.post("/webhooks/elevenlabs", **signed({"type": "post_call_transcription", "data": {
        "conversation_id": "conv9", "transcript": [{"role": "user", "message": "We picked it because the jury checks it."}]}})).json()
    assert result["answered"] == gap["id"]


def test_talk_page_has_the_widget_when_the_agent_exists(client, monkeypatch):
    gap = wout_gap(client)
    assert "not configured" in client.get(f"/gaps/{gap['id']}/talk").text
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "agent_1")
    page = client.get(f"/gaps/{gap['id']}/talk").text
    assert "<elevenlabs-convai" in page and "agent_1" in page and gap["id"] in page
