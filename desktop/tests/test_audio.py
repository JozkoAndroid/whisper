import numpy as np

from hlas import audio

SR = audio.SAMPLE_RATE


def tone(seconds, amp=3000, freq=220):
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.int16)


def silence(seconds):
    return np.zeros(int(seconds * SR), np.int16)


def test_wav_roundtrip():
    x = tone(1.0)
    assert np.array_equal(audio.from_wav(audio.to_wav(x)), x)


def test_resample_from_48k():
    import io, wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(48000)
        w.writeframes(np.zeros((48000, 2), np.int16).tobytes())
    assert len(audio.from_wav(buf.getvalue())) == SR


def test_silence_detection():
    assert audio.is_silent(silence(2))
    assert audio.is_silent(tone(0.1))
    assert not audio.is_silent(np.concatenate([silence(1), tone(0.5), silence(1)]))


def test_trim_silence():
    x = np.concatenate([silence(2), tone(1), silence(2)])
    y = audio.trim_silence(x)
    assert 1.0 <= len(y) / SR <= 1.6


def test_split_long_cuts_at_quiet_point():
    x = np.concatenate([tone(235), silence(1), tone(30)])
    parts = audio.split_long(x, max_seconds=240)
    assert len(parts) == 2
    assert sum(len(p) for p in parts) == len(x)
    assert 235 <= len(parts[0]) / SR <= 236


def test_segments_from_marks():
    x = np.arange(SR * 10, dtype=np.int16)
    segs = audio.segments_from_marks(x, [(0, "auto"), (SR * 4, "de"), (SR * 4 + 100, "en")])
    assert [l for _, l in segs] == ["auto", "en"]
    assert len(segs[0][0]) == SR * 4
    # a mark right at the start replaces the initial language
    segs = audio.segments_from_marks(x, [(0, "auto"), (SR // 10, "sk")])
    assert [l for _, l in segs] == ["sk"] and len(segs[0][0]) == len(x)
