"""Tiny text-based language guess: is this English, German, or something else?

The multilingual speech model handles English and German very well, but it
often writes Slovak as Polish or Czech. So after a first pass we look at the
text: if it is clearly English or German we keep it, otherwise the audio is
re-run through the Slovak model. Keep in sync with android/.../LangId.kt.
"""

from __future__ import annotations

import re

EN = set("""the a an and or but of to in on at for with from by is are was were be been being it this that
these those i you he she we they me him her us them my your our their not no yes do does did have has had
will would can could should just so if then than what when where who why how there here about as up out
all very really okay ok please thanks thank because also into over get got go going know think want need
like make sure let's i'm it's don't that's""".split())

DE = set("""der die das den dem des ein eine einen einem einer und oder aber nicht ist sind war waren bin bist
sein ich du er sie es wir ihr mich mir dich dir uns euch mein dein sein unser mit von zu im in am auf an
für bei aus nach über unter auch noch schon nur so wie was wer wo wann warum wenn dass weil ja nein doch
hat habe haben hatte wird werden kann können muss müssen soll will möchte bitte danke gut heute morgen
jetzt hier da dann mal sehr gerne kein keine nichts etwas alles man""".split())

SK = set("""a aj ale alebo že sa si som sme ste sú je bol bola bolo by na v vo z zo do od pre pri po o k ku s so
ja ty on ona ono my vy oni mi ti mu jej nám vám ich ma ťa ho môj tvoj náš váš tak ako čo kto kde kedy prečo
áno nie no už ešte len iba veľmi dobre teraz dnes zajtra včera tu tam toto tento táto ten to tie tí
mám máš má máme máte majú môžem môžeš môže potrebujem chcem chceš prosím ďakujem""".split())
# Polish and Czech function words: the base model writes Slovak speech in these spellings.
SK |= set("""w jest się nie czy jak mnie mi ten ta to tylko bardzo proszę dzień jutro dzisiaj mam masz ma
jsem jsi jsme jste není ještě také když protože abych proto jenom hodně děkuji prosím""".split())

SLAVIC_CHARS = re.compile(r"[čďľĺňŕšťžôřůěłąęśźżńćщъыэюя]")
GERMAN_CHARS = re.compile(r"[ßöü]")
WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?", re.UNICODE)


def scores(text: str) -> dict[str, float]:
    words = [w.lower() for w in WORD.findall(text)]
    n = len(words)
    if n == 0:
        return {"en": 0.0, "de": 0.0, "sk": 0.0, "n": 0}
    en = sum(w in EN for w in words) / n
    de = sum(w in DE for w in words) / n
    sk = sum(w in SK for w in words) / n
    low = text.lower()
    sk += min(0.3, len(SLAVIC_CHARS.findall(low)) / max(1, n) * 0.5)
    de += min(0.2, len(GERMAN_CHARS.findall(low)) / max(1, n) * 0.5)
    return {"en": en, "de": de, "sk": sk, "n": n}


def guess(text: str) -> str:
    """Return "en", "de", "sk" (meaning: Slovak or a Slavic look-alike), or ""
    when there is too little text to tell."""
    s = scores(text)
    if s["n"] == 0:
        return ""
    best = max(("en", "de", "sk"), key=lambda k: s[k])
    if s[best] < 0.12:
        # No function words at all: only trust Slavic letters.
        return "sk" if SLAVIC_CHARS.search(text.lower()) else ""
    return best


def pick(base_text: str, sk_text: str) -> str:
    """Both models heard the same phrase. Return "base" or "sk": whichever
    output reads more like real text in that model's languages. The Slovak
    model turns English/German into nonsense, and the base model turns
    Slovak into Polish-like text, so the wrong one scores low."""
    b, k = scores(base_text), scores(sk_text)
    base_conf = max(b["en"], b["de"])
    sk_conf = k["sk"]
    if "<unk>" in base_text:
        base_conf -= 0.2
    if "<unk>" in sk_text:
        sk_conf -= 0.2
    if b["sk"] > base_conf:  # the base model itself produced Slavic-looking text
        return "sk"
    return "sk" if sk_conf > base_conf else "base"
