"""The full pipeline: audio -> speech-to-text -> cleanup -> text.

This is the part other projects import:

    from hlas import Transcriber
    t = Transcriber()                      # uses the saved config / env keys
    result = t.transcribe_file("note.wav")
    print(result.text)
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from . import audio, cleanup, stt
from .config import Config


AUDIO_EXT = {
    "audio/webm": ".webm", "video/webm": ".webm", "audio/ogg": ".ogg", "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/m4a": ".m4a",
    "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/flac": ".flac",
}


@dataclass
class Result:
    text: str  # final text (cleaned if cleanup ran)
    raw: str  # what the speech model returned
    languages: list[str] = field(default_factory=list)
    seconds_audio: float = 0.0
    seconds_stt: float = 0.0
    seconds_cleanup: float = 0.0
    warning: str | None = None

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "raw": self.raw,
            "languages": self.languages,
            "seconds_audio": round(self.seconds_audio, 2),
            "seconds_stt": round(self.seconds_stt, 2),
            "seconds_cleanup": round(self.seconds_cleanup, 2),
            "warning": self.warning,
        }


class Transcriber:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config.load()
        self._pool = ThreadPoolExecutor(max_workers=6)

    # --- entry points -------------------------------------------------------

    def transcribe_file(self, path: str, language: str | None = None, cleanup_on: bool | None = None,
                        coding: bool = False) -> Result:
        import mimetypes
        import os

        with open(path, "rb") as f:
            data = f.read()
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        return self.transcribe_bytes(data, os.path.basename(path), mime, language, cleanup_on, coding)

    def transcribe_bytes(self, data: bytes, filename: str = "audio", mime: str = "application/octet-stream",
                         language: str | None = None, cleanup_on: bool | None = None,
                         coding: bool = False) -> Result:
        """Any audio the speech API accepts (wav, mp3, m4a, webm, ogg...).
        WAV gets silence trimming and chunking; other formats are sent as is."""
        if data[:4] == b"RIFF":
            return self.transcribe_wav(data, language, cleanup_on, coding)
        cfg = self.cfg
        if "." not in filename:
            filename += AUDIO_EXT.get(mime.split(";")[0].strip().lower(), ".webm")
        t0 = time.monotonic()
        raw, lang = stt.transcribe(data, language or cfg.language, cfg, filename, mime)
        t1 = time.monotonic()
        text, warning = raw, None
        if (cfg.cleanup if cleanup_on is None else cleanup_on) and raw:
            text, warning = cleanup.clean(raw, cfg, coding=coding)
        return Result(text=text, raw=raw, languages=[lang] if lang else [], seconds_stt=t1 - t0,
                      seconds_cleanup=time.monotonic() - t1, warning=warning)

    def transcribe_wav(self, wav: bytes, language: str | None = None, cleanup_on: bool | None = None,
                       coding: bool = False) -> Result:
        samples = audio.from_wav(wav)
        return self.transcribe_segments([(samples, language or self.cfg.language)], cleanup_on, coding)

    def transcribe_segments(self, segments: list[tuple[np.ndarray, str]], cleanup_on: bool | None = None,
                            coding: bool = False) -> Result:
        """segments: [(int16 samples @16k, lang)], lang in auto/sk/de/en."""
        cfg = self.cfg
        total = sum(len(s) for s, _ in segments) / audio.SAMPLE_RATE

        # Trim silence, drop silent parts, split very long parts.
        jobs: list[tuple[np.ndarray, str]] = []
        for samples, lang in segments:
            samples = audio.trim_silence(samples)
            if audio.is_silent(samples):
                continue
            for chunk in audio.split_long(samples):
                jobs.append((chunk, lang))
        if not jobs:
            return Result(text="", raw="", seconds_audio=total, warning="No speech detected")

        if cfg.stt_provider == "local":
            from . import local

            if not local.models_ready():
                local.download_cli()
        t0 = time.monotonic()
        futures = [self._pool.submit(stt.transcribe, audio.to_wav(c), lang, cfg) for c, lang in jobs]
        parts = [f.result() for f in futures]  # raises SttError
        t1 = time.monotonic()

        raw = join_parts([p[0] for p in parts])
        langs = []
        for _, lang in parts:
            for l in (lang or "").split(","):
                if l and l != "auto" and l not in langs:
                    langs.append(l)

        warning = None
        text = raw
        use_cleanup = cfg.cleanup if cleanup_on is None else cleanup_on
        if use_cleanup and raw:
            text, warning = cleanup.clean(raw, cfg, coding=coding)
        t2 = time.monotonic()
        return Result(text=text, raw=raw, languages=langs, seconds_audio=total,
                      seconds_stt=t1 - t0, seconds_cleanup=t2 - t1, warning=warning)


def join_parts(parts: list[str]) -> str:
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        out = f"{out} {p}" if out else p
    return out
