import numpy as np

from hlas import langid, local
from hlas.audio import SAMPLE_RATE as SR


def test_guess():
    assert langid.guess("Können wir das Meeting bitte auf Donnerstag verschieben?") == "de"
    assert langid.guess("Ask not what your country can do for you") == "en"
    assert langid.guess("Potrzebujem, aby si my do piatku posał tu zmluvu") == "sk"  # base model's Polish-ish Slovak
    assert langid.guess("Dobrý deň, zajtra o piatej máme stretnutie") == "sk"
    assert langid.guess("") == ""


def test_pick():
    # Slovak audio: base model writes Polish-ish text, Slovak model gets it right
    assert langid.pick("Ahoy Peter. Posse meeting report.", "Pošli mi ten report.") == "sk"
    assert langid.pick("Potrzebujem, aby si my do piatku", "potrebujem, aby si mi do piatku") == "sk"
    # English/German audio: the Slovak model produces nonsense
    assert langid.pick("Ask not what your country can do for you.", "ask noty k do fory. ask Watt<unk> do fory") == "base"
    assert langid.pick("Können wir das Meeting bitte auf Donnerstag verschieben?",
                       "Körönvít a métingét autonósták Fesében,") == "base"
    assert langid.pick("As soon as possible, because the deadline is tomorrow.", "") == "base"


def tone(sec):
    t = np.arange(int(sec * SR)) / SR
    return (3000 * np.sin(2 * np.pi * 220 * t)).astype(np.int16)


def gap(sec):
    return np.zeros(int(sec * SR), np.int16)


def test_split_phrases():
    x = np.concatenate([tone(3), gap(0.7), tone(2), gap(0.2), tone(2), gap(0.7), tone(0.5)])
    parts = local.split_phrases(x)
    # short pause (0.2 s) does not split; the 0.5 s tail is glued to the previous phrase
    assert len(parts) == 2
    assert sum(len(p) for p in parts) == len(x)


def test_engine_routes_each_phrase(monkeypatch):
    e = local.LocalEngine()
    outputs = {
        ("base", 0): "Ahoy Peter. Posse meeting report.", ("sk", 0): "Ahoj Peter, pošli mi ten report.",
        ("base", 1): "As soon as possible, because the deadline is tomorrow.", ("sk", 1): "As sun as posibl",
    }
    order = {}

    def fake_decode(name, x, hotwords=None):
        idx = order.setdefault(len(x), len(order))
        return outputs[(name, idx)]

    monkeypatch.setattr(e, "decode", fake_decode)
    x = np.concatenate([tone(2.5), gap(0.7), tone(3.5)])
    text, langs = e.transcribe(x, "auto", [])
    assert text == "Ahoj Peter, pošli mi ten report. As soon as possible, because the deadline is tomorrow."
    assert langs == ["sk", "en"]


def test_forced_language_uses_one_model(monkeypatch):
    e = local.LocalEngine()
    calls = []
    monkeypatch.setattr(e, "decode", lambda name, x, hw=None: calls.append(name) or "text")
    e.transcribe(tone(2), "sk", [])
    e.transcribe(tone(2), "de", [])
    assert calls == ["sk", "base"]


def test_models_ready_false_in_empty_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert not local.models_ready()
