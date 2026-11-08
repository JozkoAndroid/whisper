"""Speech-to-text providers.

openai      gpt-transcribe, takes a *list* of expected languages, which is what
            makes Slovak/German/English mixing in one sentence work. Default.
elevenlabs  Scribe v2, very strong on European languages; good second choice.
groq        Whisper large-v3 on Groq: the fastest, cheapest, weakest at mixing.
local       faster-whisper on your own machine: offline, needs a good GPU to be fast.

Each provider takes 16 kHz mono WAV bytes and returns (text, language).
"""

from __future__ import annotations

import re
import threading

import httpx2 as httpx
import numpy as np

from .config import Config

TIMEOUT = httpx.Timeout(90.0, connect=10.0)

DICTATION_PROMPT = (
    "Dictated text. The speaker may switch between Slovak, German and English, "
    "even mid-sentence. Write every word in the language it was spoken in, with "
    "correct diacritics (á, ä, č, ď, é, í, ĺ, ľ, ň, ó, ô, ŕ, š, ť, ú, ý, ž, ö, ü, ß). "
    "Never translate."
)

WHISPER_LANG_NAMES = {"slovak": "sk", "german": "de", "english": "en", "czech": "cs"}
# When Whisper detects a language we did not ask for, map it to the closest
# of ours (it often hears Slovak as Czech or Polish, German as Dutch).
NEAREST = {
    "czech": "sk", "polish": "sk", "slovenian": "sk", "croatian": "sk", "serbian": "sk",
    "bosnian": "sk", "ukrainian": "sk", "russian": "sk", "cs": "sk", "pl": "sk",
    "dutch": "de", "luxembourgish": "de", "danish": "de", "swedish": "de", "norwegian": "de",
    "afrikaans": "de", "nl": "de",
}


class SttError(RuntimeError):
    pass


_client: httpx.Client | None = None
_client_lock = threading.Lock()


def http() -> httpx.Client:
    """One shared keep-alive client: reusing the TLS connection saves
    100-300 ms per dictation."""
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(timeout=TIMEOUT, http2=False)
        return _client


def warm_up(cfg: Config) -> None:
    """Open the TLS connection while the user is still talking."""
    url = {
        "openai": "https://api.openai.com/v1/models",
        "elevenlabs": "https://api.elevenlabs.io/v1/models",
        "groq": "https://api.groq.com/openai/v1/models",
    }.get(cfg.stt_provider)
    if not url:
        return
    try:
        http().head(url, timeout=5.0)
    except Exception:
        pass


def _clean_terms(terms: list[str], limit: int) -> list[str]:
    out = []
    for t in terms:
        t = re.sub(r"[<>\r\n]", " ", t).strip()
        if t and t not in out:
            out.append(t[:100])
    return out[:limit]


def _check(resp: httpx.Response, provider: str) -> dict:
    if resp.status_code == 401:
        raise SttError(f"{provider}: invalid API key")
    if resp.status_code == 429:
        raise SttError(f"{provider}: rate limited or out of credit")
    if resp.status_code >= 400:
        raise SttError(f"{provider}: HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        return resp.json()
    except ValueError as e:
        raise SttError(f"{provider}: bad response") from e


def transcribe_openai(wav: bytes, lang: str, cfg: Config, filename: str = "audio.wav",
                     mime: str = "audio/wav") -> tuple[str, str]:
    key = cfg.key("openai_api_key")
    if not key:
        raise SttError("OpenAI API key missing (Settings)")
    model = cfg.openai_model
    data: dict = {"model": model}
    if model == "gpt-transcribe":
        data["languages[]"] = [lang] if lang != "auto" else list(cfg.languages)
        data["prompt"] = DICTATION_PROMPT
        terms = _clean_terms(cfg.vocabulary, 100)
        if terms:
            data["keywords[]"] = terms
    else:  # older models: one language hint, vocabulary goes in the prompt
        if lang != "auto":
            data["language"] = lang
        vocab = ", ".join(_clean_terms(cfg.vocabulary, 50))
        data["prompt"] = DICTATION_PROMPT + (f" Vocabulary: {vocab}." if vocab else "")
    resp = http().post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {key}"},
        data=data,
        files={"file": (filename, wav, mime)},
    )
    body = _check(resp, "OpenAI")
    detected = lang
    langs = body.get("languages") or []
    if lang == "auto" and langs and isinstance(langs[0], dict):
        detected = langs[0].get("code", "auto")
    elif lang == "auto" and body.get("language"):
        detected = WHISPER_LANG_NAMES.get(str(body["language"]).lower(), str(body["language"]))
    return (body.get("text") or "").strip(), detected


def transcribe_elevenlabs(wav: bytes, lang: str, cfg: Config, filename: str = "audio.wav",
                         mime: str = "audio/wav") -> tuple[str, str]:
    key = cfg.key("elevenlabs_api_key")
    if not key:
        raise SttError("ElevenLabs API key missing (Settings)")
    data: dict = {
        "model_id": cfg.elevenlabs_model,
        "tag_audio_events": "false",
        "timestamps_granularity": "none",
    }
    if lang != "auto":
        data["language_code"] = lang
    terms = _clean_terms(cfg.vocabulary, 100)
    if terms:
        data["keyterms"] = terms
    resp = http().post(
        "https://api.elevenlabs.io/v1/speech-to-text",
        headers={"xi-api-key": key},
        data=data,
        files={"file": (filename, wav, mime)},
    )
    body = _check(resp, "ElevenLabs")
    code = str(body.get("language_code") or lang)
    code = {"slk": "sk", "deu": "de", "ger": "de", "eng": "en"}.get(code, code)
    return (body.get("text") or "").strip(), code


def transcribe_groq(wav: bytes, lang: str, cfg: Config, filename: str = "audio.wav",
                   mime: str = "audio/wav") -> tuple[str, str]:
    key = cfg.key("groq_api_key")
    if not key:
        raise SttError("Groq API key missing (Settings)")

    def call(language: str | None) -> dict:
        vocab = ", ".join(_clean_terms(cfg.vocabulary, 40))
        data = {
            "model": cfg.groq_model,
            "response_format": "verbose_json",
            "temperature": "0",
            # Whisper prompts are style hints; keep them short (224 token cap).
            "prompt": ("Slovenčina, Deutsch, English. " + (vocab + "." if vocab else "")).strip(),
        }
        if language:
            data["language"] = language
        resp = http().post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            data=data,
            files={"file": (filename, wav, mime)},
        )
        return _check(resp, "Groq")

    body = call(lang if lang != "auto" else None)
    name = str(body.get("language", "")).lower()
    detected = WHISPER_LANG_NAMES.get(name, name)
    if lang == "auto" and detected not in cfg.languages:
        retry = NEAREST.get(name, "en")
        if retry not in cfg.languages:
            retry = cfg.languages[0]
        body = call(retry)
        detected = retry
    return (body.get("text") or "").strip(), detected


_local_model = None
_local_lock = threading.Lock()


def transcribe_local(wav: bytes, lang: str, cfg: Config, filename: str = "audio.wav",
                     mime: str = "audio/wav") -> tuple[str, str]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise SttError("Local mode needs: pip install hlas[local]") from e
    from .audio import from_wav

    if not wav.startswith(b"RIFF"):
        raise SttError("Local mode accepts WAV audio only")

    global _local_model
    with _local_lock:
        if _local_model is None:
            _local_model = WhisperModel(cfg.local_model, device="auto", compute_type="default")
        model = _local_model
    audio = from_wav(wav).astype(np.float32) / 32768.0
    vocab = ", ".join(_clean_terms(cfg.vocabulary, 40))
    prompt = "Slovenčina, Deutsch, English." + (f" {vocab}." if vocab else "")
    language = lang if lang != "auto" else None
    if language is None:
        # Restrict detection to our three languages (Whisper likes to say Czech).
        _, _, probs = model.detect_language(audio)  # type: ignore[attr-defined]
        allowed = [(p, l) for l, p in probs if l in cfg.languages]
        language = max(allowed)[1] if allowed else cfg.languages[0]
    kwargs = dict(language=language, initial_prompt=prompt, beam_size=5, vad_filter=True,
                  condition_on_previous_text=False)
    segments, info = model.transcribe(audio, **kwargs)
    text = " ".join(s.text.strip() for s in segments)
    return text.strip(), language


PROVIDERS = {
    "openai": transcribe_openai,
    "elevenlabs": transcribe_elevenlabs,
    "groq": transcribe_groq,
    "local": transcribe_local,
}


def transcribe(wav: bytes, lang: str, cfg: Config, filename: str = "audio.wav",
               mime: str = "audio/wav") -> tuple[str, str]:
    try:
        fn = PROVIDERS[cfg.stt_provider]
    except KeyError:
        raise SttError(f"unknown provider {cfg.stt_provider!r}")
    try:
        return fn(wav, lang, cfg, filename, mime)
    except httpx.TimeoutException as e:
        raise SttError(f"{cfg.stt_provider}: timed out") from e
    except httpx.TransportError as e:
        raise SttError(f"{cfg.stt_provider}: network error ({e.__class__.__name__})") from e
