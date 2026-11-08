"""Hlas: push-to-talk dictation for Slovak, German and English.

Library use:

    from hlas import Transcriber
    print(Transcriber().transcribe_file("memo.m4a").text)
"""

from .config import Config
from .pipeline import Result, Transcriber
from .stt import SttError

__all__ = ["Config", "Result", "SttError", "Transcriber"]
__version__ = "0.1.0"
