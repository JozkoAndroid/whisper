import httpx2 as httpx
import pytest

from hlas import stt
from hlas.config import Config


def mock(monkeypatch, handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(stt, "http", lambda: client)


def form(request):
    body = request.read().decode("latin-1")
    return body


def test_openai_gpt_transcribe_sends_languages_and_keywords(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = form(request)
        return httpx.Response(200, json={"text": " Ahoj, wie geht's? ", "languages": [{"code": "sk"}]})

    mock(monkeypatch, handler)
    cfg = Config(openai_api_key="sk-test", vocabulary=["Hlas", "bad<term>"])
    text, lang = stt.transcribe(b"RIFF....", "auto", cfg)
    assert text == "Ahoj, wie geht's?" and lang == "sk"
    assert seen["url"].endswith("/v1/audio/transcriptions")
    assert seen["auth"] == "Bearer sk-test"
    b = seen["body"]
    for v in ("sk", "de", "en"):
        assert f'name="languages[]"\r\n\r\n{v}' in b
    assert 'name="keywords[]"\r\n\r\nHlas' in b
    assert "bad term" in b and "<term>" not in b
    assert 'name="language"' not in b


def test_openai_forced_language(monkeypatch):
    seen = {}
    mock(monkeypatch, lambda r: (seen.setdefault("b", form(r)), httpx.Response(200, json={"text": "Hallo"}))[1])
    stt.transcribe(b"x", "de", Config(openai_api_key="k"))
    assert seen["b"].count('name="languages[]"') == 1 and 'languages[]"\r\n\r\nde' in seen["b"]


def test_elevenlabs(monkeypatch):
    seen = {}

    def handler(r):
        seen["key"] = r.headers["xi-api-key"]
        seen["b"] = form(r)
        return httpx.Response(200, json={"text": "Dobrý deň", "language_code": "slk"})

    mock(monkeypatch, handler)
    text, lang = stt.transcribe(b"x", "auto", Config(stt_provider="elevenlabs", elevenlabs_api_key="e"))
    assert (text, lang) == ("Dobrý deň", "sk")
    assert seen["key"] == "e" and "scribe_v2" in seen["b"] and "language_code" not in seen["b"]


def test_groq_retries_czech_as_slovak(monkeypatch):
    calls = []

    def handler(r):
        b = form(r)
        calls.append(b)
        if 'name="language"' in b:
            return httpx.Response(200, json={"text": "Dobrý deň, ako sa máš", "language": "slovak"})
        return httpx.Response(200, json={"text": "Dobrý den, jak se máš", "language": "czech"})

    mock(monkeypatch, handler)
    text, lang = stt.transcribe(b"x", "auto", Config(stt_provider="groq", groq_api_key="g"))
    assert len(calls) == 2 and lang == "sk" and text.startswith("Dobrý deň")


def test_errors(monkeypatch):
    mock(monkeypatch, lambda r: httpx.Response(401, json={}))
    with pytest.raises(stt.SttError, match="invalid API key"):
        stt.transcribe(b"x", "auto", Config(openai_api_key="bad"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(stt.SttError, match="missing"):
        stt.transcribe(b"x", "auto", Config())
