"""Put text into whatever window has focus: copy to the clipboard, send the
paste shortcut, then restore the previous clipboard text."""

from __future__ import annotations

import sys
import threading
import time


def paste_text(text: str, restore: bool = True, paste: bool = True) -> None:
    import pyperclip

    previous = None
    if restore and paste:
        try:
            previous = pyperclip.paste()
        except Exception:
            previous = None
    pyperclip.copy(text)
    if not paste:
        return
    time.sleep(0.04)  # let the clipboard owner settle
    from pynput.keyboard import Controller, Key

    kb = Controller()
    mod = Key.cmd if sys.platform == "darwin" else Key.ctrl
    with kb.pressed(mod):
        kb.press("v")
        kb.release("v")
    if previous is not None:
        # Some apps (Electron, browsers) read the clipboard asynchronously.
        def _restore():
            try:
                if pyperclip.paste() == text:
                    pyperclip.copy(previous)
            except Exception:
                pass

        threading.Timer(0.8, _restore).start()
