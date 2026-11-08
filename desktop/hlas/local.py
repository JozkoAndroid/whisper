"""Offline, free speech recognition with two open models (via sherpa-onnx):

  base  NVIDIA Parakeet TDT 0.6B v3 (25 European languages, CC-BY-4.0).
        Very good at English and German, but tends to write Slovak as Polish.
  sk    KInIT's Slovak fine-tune of the same model (CC-BY-4.0). About 4x fewer
        errors on real Slovak speech than the base model, but it can no longer
        do English or German.

So the audio is cut into phrases at pauses, both models transcribe each phrase
(in parallel), and the output that reads like real text wins: Slovak from the
Slovak model, English/German from the base model. That handles switching
languages between phrases. Both models are fast on an ordinary CPU.

Models (~1.3 GB) are downloaded once into the Hlas folder.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import logging
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import numpy as np

from . import audio, langid
from .config import config_dir

log = logging.getLogger("hlas")

RELEASE = "https://github.com/JozkoAndroid/whisper/releases/download/models-v1/"
# Second source for the base model (same NVIDIA model, converted by the sherpa-onnx author).
BASE_MIRROR = "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/resolve/main/"


# GitHub release asset ids of models-v1. The API address is far more reliable than
# github.com/.../releases/download, which often answers 504.
ASSET_IDS = {
    ("base", "decoder.int8.onnx"): 723428492, ("base", "encoder.int8.onnx"): 723428493,
    ("base", "joiner.int8.onnx"): 723428494, ("base", "tokens.txt"): 723428496,
    ("sk", "decoder.int8.onnx"): 723428508, ("sk", "encoder.int8.onnx"): 723428512,
    ("sk", "joiner.int8.onnx"): 723428518, ("sk", "tokens.txt"): 723428516,
}
API_ASSET = "https://api.github.com/repos/JozkoAndroid/whisper/releases/assets/"


def urls_for(model: str, file: str) -> list[str]:
    """Sources in order of preference."""
    urls = []
    if model == "base":
        urls.append(BASE_MIRROR + file)  # Hugging Face: fast and reliable
    if (model, file) in ASSET_IDS:
        urls.append(API_ASSET + str(ASSET_IDS[(model, file)]))
    urls.append(RELEASE + f"parakeet-{model}-{file}")
    return urls


_ssl_ctx = None


def ssl_context():
    """System certificates plus certifi's, so downloads work even on PCs with
    an outdated certificate store."""
    global _ssl_ctx
    if _ssl_ctx is None:
        import ssl

        ctx = ssl.create_default_context()
        try:
            import certifi

            ctx.load_verify_locations(certifi.where())
        except Exception:
            pass
        _ssl_ctx = ctx
    return _ssl_ctx
FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
MODELS = ("base", "sk")


class ModelMissing(RuntimeError):
    pass


def model_dir(name: str) -> Path:
    return config_dir() / "models" / f"parakeet-{name}"


def models_ready() -> bool:
    return all((model_dir(m) / f).is_file() for m in MODELS for f in FILES)


TOTAL_BYTES = 1_341_000_000  # approximate, only for the progress display


def _fetch(urls: list[str], dest: Path, on_bytes: Callable[[int], None], attempts: int = 8) -> None:
    """Download to dest, resuming a partial file and retrying on errors, then
    trying the next source. No HEAD request: GitHub's signed links only allow GET."""
    part = dest.with_suffix(dest.suffix + ".part")
    last = "unknown error"
    for url in urls:
        for attempt in range(attempts):
            have = part.stat().st_size if part.exists() else 0
            headers = {"User-Agent": "hlas", "Accept": "application/octet-stream"}
            if have:
                headers["Range"] = f"bytes={have}-"
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60,
                                            context=ssl_context()) as r:
                    resumed = r.status == 206
                    if not resumed and have:
                        on_bytes(-have)  # server ignored the range: start over
                        have = 0
                    length = int(r.headers.get("Content-Length") or 0)
                    expected = have + length if length else 0
                    with open(part, "ab" if resumed else "wb") as out:
                        while True:
                            chunk = r.read(1 << 20)
                            if not chunk:
                                break
                            out.write(chunk)
                            on_bytes(len(chunk))
                if expected and part.stat().st_size != expected:
                    raise OSError("connection closed early")
                part.replace(dest)
                return
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code} from {urllib.parse.urlparse(url).netloc}"
                log.warning("download %s: %s", url, last)
                if e.code == 416 and have:  # broken partial file: start over
                    on_bytes(-have)
                    part.unlink(missing_ok=True)
                elif e.code < 500 and e.code not in (408, 429):
                    break  # this source will not work; try the next one
            except Exception as e:  # network, SSL, timeouts, disk
                last = f"{type(e).__name__}: {e}"
                log.warning("download %s: %s", url, last)
                if isinstance(e, OSError) and getattr(e, "errno", None) == 28:
                    raise RuntimeError("not enough disk space (need 1.3 GB)") from e
            time.sleep(min(10, 1 + attempt))  # GitHub often answers 504 once, then works
    raise RuntimeError(f"could not download {dest.name}: {last}")


def download_models(progress: Callable[[float, str], None] | None = None) -> None:
    """Download any missing model files. progress(fraction 0..1, message)."""
    todo = [(m, f) for m in MODELS for f in FILES if not (model_dir(m) / f).is_file()]
    if not todo:
        return
    done = sum((model_dir(m) / f).stat().st_size for m in MODELS for f in FILES if (model_dir(m) / f).is_file())

    def on_bytes(n: int) -> None:
        nonlocal done
        done += n
        if progress:
            pct = min(99, done * 100 // TOTAL_BYTES)
            progress(pct / 100, f"Downloading speech models {pct}%")

    for m, f in todo:
        dest = model_dir(m) / f
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")
        if part.exists():
            done += part.stat().st_size
        _fetch(urls_for(m, f), dest, on_bytes)
    if progress:
        progress(1.0, "Speech models downloaded")


def split_phrases(x: np.ndarray, min_pause: float = 0.45, min_phrase: float = 1.5) -> list[np.ndarray]:
    """Cut at pauses so each phrase can be routed to the right language model."""
    win = audio.SAMPLE_RATE // 50
    n = len(x) // win
    if n == 0:
        return [x]
    energy = np.sqrt(np.mean(x[: n * win].astype(np.float32).reshape(n, win) ** 2, axis=1))
    quiet = energy < 120.0 * 2.5
    cuts, run_start = [], None
    for i, q in enumerate(quiet):
        if q and run_start is None:
            run_start = i
        elif not q and run_start is not None:
            if (i - run_start) * win >= min_pause * audio.SAMPLE_RATE:
                cuts.append(((run_start + i) // 2) * win)
            run_start = None
    bounds = [0] + cuts + [len(x)]
    phrases = [x[a:b] for a, b in zip(bounds, bounds[1:]) if b > a]
    merged: list[np.ndarray] = []
    for p in phrases:  # glue very short bits to the previous phrase
        if merged and len(p) < min_phrase * audio.SAMPLE_RATE:
            merged[-1] = np.concatenate([merged[-1], p])
        else:
            merged.append(p)
    if len(merged) > 1 and len(merged[0]) < min_phrase * audio.SAMPLE_RATE:
        merged[1] = np.concatenate([merged[0], merged[1]])
        merged.pop(0)
    return merged


class LocalEngine:
    def __init__(self):
        self._rec: dict[str, object] = {}
        self._locks = {m: threading.Lock() for m in MODELS}
        self._load_lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=2)

    def _recognizer(self, name: str):
        with self._load_lock:
            if name not in self._rec:
                if not models_ready():
                    raise ModelMissing("Speech models not downloaded yet")
                import sherpa_onnx

                d = model_dir(name)
                self._rec[name] = sherpa_onnx.OfflineRecognizer.from_transducer(
                    encoder=str(d / "encoder.int8.onnx"),
                    decoder=str(d / "decoder.int8.onnx"),
                    joiner=str(d / "joiner.int8.onnx"),
                    tokens=str(d / "tokens.txt"),
                    num_threads=max(1, min(8, (os.cpu_count() or 4) // 2)),  # two models run in parallel
                    model_type="nemo_transducer",
                    # Greedy: sherpa-onnx's beam search (needed for hotwords) sometimes
                    # returns empty text with these TDT models. Vocabulary is applied
                    # by the cleanup step instead.
                    decoding_method="greedy_search",
                )
            return self._rec[name]

    def preload(self) -> None:
        for m in MODELS:
            self._recognizer(m)

    def decode(self, name: str, x: np.ndarray, hotwords: list[str] | None = None) -> str:
        rec = self._recognizer(name)
        with self._locks[name]:
            stream = rec.create_stream()
            stream.accept_waveform(audio.SAMPLE_RATE, x.astype(np.float32) / 32768.0)
            rec.decode_stream(stream)
            return stream.result.text.strip()

    def transcribe(self, x: np.ndarray, lang: str, vocabulary: list[str]) -> tuple[str, list[str]]:
        """x: int16 @16 kHz. lang: auto/sk/de/en. Returns (text, languages)."""
        if lang == "sk":
            return self.decode("sk", x, vocabulary), ["sk"]
        if lang in ("de", "en"):
            return self.decode("base", x, vocabulary), [lang]
        texts, langs = [], []
        for phrase in split_phrases(x):
            # Run both models at once and keep the output that reads right.
            sk_future = self._pool.submit(self.decode, "sk", phrase, vocabulary)
            base_text = self.decode("base", phrase, vocabulary)
            sk_text = sk_future.result()
            if langid.pick(base_text, sk_text) == "sk":
                text, guess = sk_text, "sk"
            else:
                text, guess = base_text, langid.guess(base_text)
            if text:
                texts.append(text.replace("<unk>", "").strip())
                if guess and guess not in langs:
                    langs.append(guess)
        return " ".join(texts), langs


_engine: LocalEngine | None = None
_engine_lock = threading.Lock()


def engine() -> LocalEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = LocalEngine()
        return _engine


def download_cli() -> None:
    err = sys.stderr  # None inside the windowed Hlas.exe

    def show(frac, msg):
        if err:
            err.write(f"\r[hlas] {msg}   ")
            err.flush()

    download_models(show)
    if err:
        err.write("\n[hlas] speech models ready\n")
