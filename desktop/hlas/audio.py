"""Audio helpers: microphone capture, WAV encoding, silence trimming, chunking.

Everything works on mono int16 numpy arrays at 16 kHz, which is what every
speech model wants anyway (smaller uploads = faster round trips).
"""

from __future__ import annotations

import io
import threading
import time
import wave

import numpy as np

SAMPLE_RATE = 16_000
# Cloud APIs accept ~25 MB; 16 kHz mono int16 is ~1.9 MB/min. Chunks are also
# sent in parallel, so long dictations finish faster.
CHUNK_SECONDS = 240


def to_wav(samples: np.ndarray, rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.asarray(samples, dtype=np.int16).tobytes())
    return buf.getvalue()


def from_wav(data: bytes) -> np.ndarray:
    """Decode a PCM WAV to mono int16 at 16 kHz (simple resample if needed)."""
    with wave.open(io.BytesIO(data), "rb") as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width == 2:
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    elif width == 4:
        x = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 65536.0
    elif width == 1:
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) * 256.0
    else:
        raise ValueError(f"unsupported WAV sample width: {width}")
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if rate != SAMPLE_RATE and len(x):
        n = int(round(len(x) * SAMPLE_RATE / rate))
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
    return np.clip(x, -32768, 32767).astype(np.int16)


def rms(samples: np.ndarray) -> float:
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))


def is_silent(samples: np.ndarray, threshold: float = 120.0) -> bool:
    """True when there is (almost) no speech. Sending silence to Whisper-style
    models makes them hallucinate ("Thanks for watching"), so we skip it."""
    if len(samples) < SAMPLE_RATE * 0.25:
        return True
    win = SAMPLE_RATE // 50  # 20 ms frames
    n = len(samples) // win
    if n == 0:
        return True
    frames = samples[: n * win].astype(np.float32).reshape(n, win)
    energy = np.sqrt(np.mean(frames**2, axis=1))
    # Need at least ~150 ms of frames clearly above the threshold.
    return int(np.sum(energy > threshold * 2.5)) < 8


def trim_silence(samples: np.ndarray, threshold: float = 120.0, pad: float = 0.25) -> np.ndarray:
    """Cut leading/trailing silence, keeping a little padding."""
    win = SAMPLE_RATE // 50
    n = len(samples) // win
    if n == 0:
        return samples
    frames = samples[: n * win].astype(np.float32).reshape(n, win)
    loud = np.where(np.sqrt(np.mean(frames**2, axis=1)) > threshold * 2.5)[0]
    if len(loud) == 0:
        return samples[:0]
    p = int(pad * SAMPLE_RATE)
    start = max(0, loud[0] * win - p)
    end = min(len(samples), (loud[-1] + 1) * win + p)
    return samples[start:end]


def split_long(samples: np.ndarray, max_seconds: int = CHUNK_SECONDS) -> list[np.ndarray]:
    """Split into chunks of at most max_seconds, cutting at the quietest
    point of the last 10 s of each chunk so words are not cut in half."""
    limit = max_seconds * SAMPLE_RATE
    out: list[np.ndarray] = []
    pos = 0
    while len(samples) - pos > limit:
        window_start = pos + limit - 10 * SAMPLE_RATE
        win = SAMPLE_RATE // 20  # 50 ms
        seg = samples[window_start : pos + limit].astype(np.float32)
        k = len(seg) // win
        energy = np.sqrt(np.mean(seg[: k * win].reshape(k, win) ** 2, axis=1))
        cut = window_start + int(np.argmin(energy)) * win + win // 2
        out.append(samples[pos:cut])
        pos = cut
    out.append(samples[pos:])
    return [c for c in out if len(c)]


class Recorder:
    """Microphone capture with language markers.

    `mark(lang)` during a recording starts a new segment in that language, so
    you can say a sentence in Slovak, press the German key, and continue in
    German; each segment is transcribed with its own language hint.
    """

    def __init__(self, device: str | int | None = None):
        self.device = device or None
        self._chunks: list[np.ndarray] = []
        self._marks: list[tuple[int, str]] = []
        self._count = 0
        self._lock = threading.Lock()
        self._stream = None
        self.level = 0.0  # live input level 0..1 for the overlay
        self.started_at = 0.0

    def _callback(self, indata, frames, time_info, status):  # sounddevice thread
        block = (indata[:, 0] * 32767).astype(np.int16) if indata.dtype != np.int16 else indata[:, 0].copy()
        with self._lock:
            self._chunks.append(block)
            self._count += len(block)
        self.level = min(1.0, rms(block) / 4000.0)

    def start(self, lang: str = "auto") -> None:
        import sounddevice as sd  # imported lazily: not needed for library/server use

        with self._lock:
            self._chunks, self._marks, self._count = [], [(0, lang)], 0
        self.started_at = time.monotonic()
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            device=self.device,
            blocksize=SAMPLE_RATE // 20,
            callback=self._callback,
        )
        self._stream.start()

    def mark(self, lang: str) -> None:
        with self._lock:
            self._marks.append((self._count, lang))

    @property
    def recording(self) -> bool:
        return self._stream is not None

    @property
    def seconds(self) -> float:
        return self._count / SAMPLE_RATE

    def stop(self) -> list[tuple[np.ndarray, str]]:
        """Stop and return [(samples, lang), ...] segments."""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
        with self._lock:
            audio = np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.int16)
            marks = list(self._marks)
        self.level = 0.0
        return segments_from_marks(audio, marks)


def segments_from_marks(audio: np.ndarray, marks: list[tuple[int, str]]) -> list[tuple[np.ndarray, str]]:
    """Turn [(sample_index, lang), ...] markers into audio segments.
    Markers closer than 0.5 s are merged (the last language wins)."""
    cleaned: list[tuple[int, str]] = []
    for idx, lang in sorted(marks, key=lambda m: m[0]):
        if cleaned and idx - cleaned[-1][0] < SAMPLE_RATE // 2:
            cleaned[-1] = (cleaned[-1][0], lang)
        else:
            cleaned.append((idx, lang))
    if not cleaned:
        cleaned = [(0, "auto")]
    cleaned[0] = (0, cleaned[0][1])
    segs = []
    for i, (start, lang) in enumerate(cleaned):
        end = cleaned[i + 1][0] if i + 1 < len(cleaned) else len(audio)
        if end > start:
            segs.append((audio[start:end], lang))
    return segs
