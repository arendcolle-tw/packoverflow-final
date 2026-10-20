from knowledge_graph import llm


class Response:
    def __init__(self, body, text=""):
        self.body, self.text = body, text

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def test_gemini_on_cloud_run_without_an_anthropic_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("K_SERVICE", "knowledge-graph")
    seen = {}
    monkeypatch.setattr(llm.httpx, "get", lambda url, **k: Response({"access_token": "t"}, text="proj"))

    def post(url, **kwargs):
        seen.update(url=url, auth=kwargs["headers"]["Authorization"])
        return Response({"candidates": [{"content": {"parts": [{"text": '{"draft": "We did X because Y.", "check_question": "Q?"}'}]}}]})

    monkeypatch.setattr(llm.httpx, "post", post)
    found = llm.ask_json("system", "user")
    assert found == {"draft": "We did X because Y.", "check_question": "Q?", "_by": "gemini"}
    assert "projects/proj/locations/us-central1/publishers/google/models/" in seen["url"] and seen["auth"] == "Bearer t"


def test_no_model_off_cloud_run_without_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    assert llm.ask_json("system", "user") is None
