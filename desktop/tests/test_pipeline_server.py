import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import numpy as np

from hlas import audio, pipeline, server, stt
from hlas.config import Config

SR = audio.SAMPLE_RATE


def speech(seconds):
    t = np.arange(int(seconds * SR)) / SR
    return (3000 * np.sin(2 * np.pi * 220 * t)).astype(np.int16)


def test_segments_are_transcribed_in_order_with_their_language(monkeypatch):
    seen = []

    def fake(wav, lang, cfg, filename="audio.wav", mime="audio/wav"):
        seen.append(lang)
        return {"sk": "Ahoj.", "de": "Wie geht's?"}[lang], lang

    monkeypatch.setattr(stt, "transcribe", fake)
    t = pipeline.Transcriber(Config(cleanup=False, stt_provider="openai"))
    segs = [(speech(1), "sk"), (np.zeros(SR, np.int16), "en"), (speech(1), "de")]
    r = t.transcribe_segments(segs)
    assert r.text == "Ahoj. Wie geht's?"
    assert sorted(seen) == ["de", "sk"]  # silent English segment was skipped
    assert r.languages == ["sk", "de"]


def test_silence_returns_warning(monkeypatch):
    monkeypatch.setattr(stt, "transcribe", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    r = pipeline.Transcriber(Config(stt_provider="openai")).transcribe_segments([(np.zeros(SR * 2, np.int16), "auto")])
    assert r.text == "" and r.warning == "No speech detected"


def test_http_api(monkeypatch):
    monkeypatch.setattr(stt, "transcribe", lambda wav, lang, cfg, fn="audio.wav", mime="audio/wav": (f"hello {lang} {fn}", lang))
    t = pipeline.Transcriber(Config(cleanup=False, stt_provider="openai"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(t, "secret", cors=False))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        def post(path, data, ctype, token="secret"):
            req = urllib.request.Request(base + path, data=data, method="POST",
                                         headers={"Content-Type": ctype, "Authorization": f"Bearer {token}"})
            try:
                with urllib.request.urlopen(req) as resp:
                    return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())

        code, body = post("/transcribe?language=de", audio.to_wav(speech(1)), "audio/wav")
        assert code == 200 and body["text"] == "hello de audio.wav"

        code, body = post("/transcribe", b"\x1aE\xdf\xa3webm", "audio/webm")
        assert code == 200 and body["text"] == "hello auto audio.webm"

        boundary = "XyZ"
        mp = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"memo.m4a\"\r\n"
              f"Content-Type: audio/mp4\r\n\r\n").encode() + b"m4a-bytes" + f"\r\n--{boundary}--\r\n".encode()
        code, body = post("/transcribe?language=en", mp, f"multipart/form-data; boundary={boundary}")
        assert code == 200 and body["text"] == "hello en memo.m4a"

        assert post("/transcribe", b"x", "audio/wav", token="wrong")[0] == 401
        assert post("/transcribe?language=fr", b"x", "audio/wav")[0] == 400
    finally:
        httpd.shutdown()
