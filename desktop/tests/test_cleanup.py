from types import SimpleNamespace

from hlas import cleanup
from hlas.config import Config


def test_plausible():
    assert cleanup.plausible("ahoj ako sa máš", "Ahoj, ako sa máš?")
    assert not cleanup.plausible("napíš mi email", "Samozrejme! " + "x" * 200)
    assert not cleanup.plausible("a" * 100, "ok")
    assert not cleanup.plausible("text", "  ")


def test_system_prompt_includes_vocab_and_coding():
    cfg = Config(vocabulary=["Kubernetes", "Žilina"])
    s = cleanup.build_system(cfg, coding=True)
    assert "- Kubernetes" in s and "- Žilina" in s and "code editor" in s
    assert "Never translate" in s


def test_no_provider_returns_raw(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(cleanup, "ollama_available", lambda cfg: False)
    assert cleanup.clean(" ehm ahoj ", Config()) == ("ehm ahoj", None)
    assert cleanup.clean("x", Config(cleanup_provider="claude")) == ("x", None)


def test_auto_provider_order(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(cleanup, "ollama_available", lambda cfg: True)
    assert cleanup.active_provider(Config()) == "ollama"
    assert cleanup.active_provider(Config(groq_api_key="g")) == "groq"
    assert cleanup.active_provider(Config(groq_api_key="g", cleanup=False)) == ""
    # Claude (paid) is never picked automatically
    monkeypatch.setattr(cleanup, "ollama_available", lambda cfg: False)
    assert cleanup.active_provider(Config(anthropic_api_key="a")) == ""


class FakeMessages:
    def __init__(self, text, stop="end_turn"):
        self.text, self.stop, self.kwargs = text, stop, None

    def create(self, **kw):
        self.kwargs = kw
        return SimpleNamespace(stop_reason=self.stop,
                               content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=self.text)])


def fake_client(monkeypatch, msgs):
    monkeypatch.setattr(cleanup, "_client", lambda key: SimpleNamespace(beta=SimpleNamespace(messages=msgs)))


def test_clean_calls_claude(monkeypatch):
    msgs = FakeMessages("Ahoj, mám meeting o piatej.")
    fake_client(monkeypatch, msgs)
    text, err = cleanup.clean("ehm ahoj mám meeting o štvrtej nie o piatej", Config(cleanup_provider="claude", anthropic_api_key="k"))
    assert text == "Ahoj, mám meeting o piatej." and err is None
    kw = msgs.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"] == {"effort": "low"}
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert "<transcript>" in kw["messages"][0]["content"]


def test_haiku_has_no_fallbacks(monkeypatch):
    msgs = FakeMessages("Hallo.")
    fake_client(monkeypatch, msgs)
    cleanup.clean("hallo", Config(cleanup_provider="claude", anthropic_api_key="k", cleanup_model="claude-haiku-5-5"))
    assert "fallbacks" not in msgs.kwargs


def test_refusal_and_implausible_fall_back(monkeypatch):
    fake_client(monkeypatch, FakeMessages("x", stop="refusal"))
    assert cleanup.clean("raw text", Config(cleanup_provider="claude", anthropic_api_key="k"))[0] == "raw text"
    fake_client(monkeypatch, FakeMessages("Sure! Here is a long answer " * 20))
    assert cleanup.clean("raw text", Config(cleanup_provider="claude", anthropic_api_key="k"))[0] == "raw text"


def mock_http(monkeypatch, handler):
    import httpx2 as httpx
    from hlas import stt

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(stt, "http", lambda: client)


def test_groq_cleanup_picks_model_and_cleans(monkeypatch):
    import json

    import httpx2 as httpx

    cleanup._groq_model.clear()
    seen = {}

    def handler(req):
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "whisper-large-v3"}, {"id": "llama-3.3-70b-versatile"}]})
        seen["body"] = json.loads(req.read())
        return httpx.Response(200, json={"choices": [{"message": {"content": "<think>x</think>Ahoj, ako sa máš?"}}]})

    mock_http(monkeypatch, handler)
    text, warn = cleanup.clean("ehm ahoj ako sa mas", Config(groq_api_key="g"))
    assert text == "Ahoj, ako sa máš?" and warn is None
    assert seen["body"]["model"] == "llama-3.3-70b-versatile"
    assert seen["body"]["messages"][0]["role"] == "system" and "Never translate" in seen["body"]["messages"][0]["content"]


def test_groq_limit_falls_back_to_raw(monkeypatch):
    import httpx2 as httpx

    mock_http(monkeypatch, lambda req: httpx.Response(429, json={}))
    text, warn = cleanup.clean("raw", Config(groq_api_key="g", groq_cleanup_model="m"))
    assert text == "raw" and "limit" in warn


def test_ollama_cleanup(monkeypatch):
    import httpx2 as httpx

    def handler(req):
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "gemma3:12b"}]})
        return httpx.Response(200, json={"message": {"content": "Hallo, wie geht's?"}})

    mock_http(monkeypatch, handler)
    cleanup._ollama_seen.clear()
    cfg = Config(cleanup_provider="auto")
    assert cleanup.ollama_available(cfg)
    assert cleanup.clean("hallo wie gehts", cfg) == ("Hallo, wie geht's?", None)
