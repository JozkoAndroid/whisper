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


def test_no_key_returns_raw(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cleanup.clean(" ehm ahoj ", Config()) == ("ehm ahoj", None)


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
    text, err = cleanup.clean("ehm ahoj mám meeting o štvrtej nie o piatej", Config(anthropic_api_key="k"))
    assert text == "Ahoj, mám meeting o piatej." and err is None
    kw = msgs.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"] == {"effort": "low"}
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert "<transcript>" in kw["messages"][0]["content"]


def test_haiku_has_no_fallbacks(monkeypatch):
    msgs = FakeMessages("Hallo.")
    fake_client(monkeypatch, msgs)
    cleanup.clean("hallo", Config(anthropic_api_key="k", cleanup_model="claude-haiku-5-5"))
    assert "fallbacks" not in msgs.kwargs


def test_refusal_and_implausible_fall_back(monkeypatch):
    fake_client(monkeypatch, FakeMessages("x", stop="refusal"))
    assert cleanup.clean("raw text", Config(anthropic_api_key="k"))[0] == "raw text"
    fake_client(monkeypatch, FakeMessages("Sure! Here is a long answer " * 20))
    assert cleanup.clean("raw text", Config(anthropic_api_key="k"))[0] == "raw text"
