"""Global hotkey: hold to talk, with hands-free lock and language keys.

Default combo is Ctrl+Win (like Wispr Flow on Windows).

    hold combo            record; release to transcribe and paste
    combo + Space         lock hands-free; tap the combo again to stop
    combo + 1 / 2 / 3     switch to Slovak / German / English from this point on
    combo + 0             back to auto (mixed) mode
    Esc                   cancel the current recording

On Windows the Space/digit/Esc presses made together with the combo are
swallowed so they don't reach the focused app.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Callable

LANG_KEYS = {"1": "sk", "2": "de", "3": "en", "0": "auto"}
ALIASES = {"win": "cmd", "super": "cmd", "meta": "cmd", "windows": "cmd", "control": "ctrl",
           "option": "alt", "escape": "esc", "altgr": "alt_gr"}


def parse_combo(text: str) -> list[str]:
    parts = [p.strip().lower() for p in text.replace(" ", "").split("+") if p.strip()]
    return [ALIASES.get(p, p) for p in parts] or ["ctrl", "cmd"]


class HotkeyMachine:
    """Pure state machine, fed with normalized key tokens. Returns True from
    down()/up() when the key should be swallowed."""

    IDLE, HOLD, LOCK = "idle", "hold", "lock"

    def __init__(self, combo: list[str], on_start: Callable[[], None], on_stop: Callable[[], None],
                 on_cancel: Callable[[], None], on_lang: Callable[[str], None],
                 on_lock: Callable[[], None] = lambda: None, clock: Callable[[], float] = time.monotonic):
        self.combo = set(combo)
        self.on_start, self.on_stop, self.on_cancel = on_start, on_stop, on_cancel
        self.on_lang, self.on_lock = on_lang, on_lock
        self.clock = clock
        self.state = self.IDLE
        self.held: set[str] = set()
        self.combo_active = False
        self.used_extra = False
        self.started = 0.0
        self.swallowed: set[str] = set()
        self.lock = threading.Lock()

    def reset(self) -> None:
        with self.lock:
            self.state = self.IDLE
            self.held.clear()
            self.combo_active = False
            self.swallowed.clear()

    def _cancel(self) -> None:
        self.state = self.IDLE
        self.on_cancel()

    def down(self, tokens: set[str]) -> bool:
        with self.lock:
            if tokens & self.combo and tokens <= self.held:
                return False  # auto-repeat
            self.held |= tokens
            was = self.combo_active
            self.combo_active = self.combo <= self.held
            if self.combo_active and not was:
                self.used_extra = False
                if self.state == self.IDLE:
                    self.state = self.HOLD
                    self.started = self.clock()
                    self.on_start()
                return False
            if tokens & self.combo:
                return False

            if self.combo_active:
                self.used_extra = True
                if self.state == self.IDLE:
                    return False
                if "space" in tokens and self.state == self.HOLD:
                    self.state = self.LOCK
                    self.on_lock()
                    return self._swallow(tokens)
                for t in tokens:
                    if t in LANG_KEYS:
                        self.on_lang(LANG_KEYS[t])
                        return self._swallow(tokens)
                if "esc" in tokens:
                    self._cancel()
                    return self._swallow(tokens)
                # Combo used as part of another shortcut (e.g. Ctrl+Win+D): drop a
                # recording that only just started.
                if self.state == self.HOLD and self.clock() - self.started < 1.0:
                    self._cancel()
                return False
            if self.state != self.IDLE and "esc" in tokens:
                self._cancel()
            return False

    def _swallow(self, tokens: set[str]) -> bool:
        self.swallowed |= tokens
        return True

    def up(self, tokens: set[str]) -> bool:
        with self.lock:
            self.held -= tokens
            was = self.combo_active
            self.combo_active = self.combo <= self.held
            if was and not self.combo_active:
                if self.state == self.HOLD:
                    self.state = self.IDLE
                    self.on_stop()
                elif self.state == self.LOCK and not self.used_extra:
                    self.state = self.IDLE
                    self.on_stop()
            if tokens & self.swallowed:
                self.swallowed -= tokens
                return True
            return False


# --- pynput adapter ---------------------------------------------------------

_WIN_VK = {
    0xA2: {"ctrl", "ctrl_l"}, 0xA3: {"ctrl", "ctrl_r"}, 0x11: {"ctrl"},
    0x5B: {"cmd", "cmd_l"}, 0x5C: {"cmd", "cmd_r"},
    0xA4: {"alt", "alt_l"}, 0xA5: {"alt", "alt_r", "alt_gr"}, 0x12: {"alt"},
    0xA0: {"shift", "shift_l"}, 0xA1: {"shift", "shift_r"}, 0x10: {"shift"},
    0x20: {"space"}, 0x1B: {"esc"}, 0x0D: {"enter"}, 0x09: {"tab"},
    0x14: {"caps_lock"}, 0x13: {"pause"}, 0x91: {"scroll_lock"},
}


def win_vk_tokens(vk: int) -> set[str]:
    if vk in _WIN_VK:
        return _WIN_VK[vk]
    if 0x30 <= vk <= 0x39:
        return {str(vk - 0x30)}
    if 0x60 <= vk <= 0x69:
        return {str(vk - 0x60)}
    if 0x41 <= vk <= 0x5A:
        return {chr(vk).lower()}
    if 0x70 <= vk <= 0x87:
        return {f"f{vk - 0x6F}"}
    return {f"vk{vk}"}


def pynput_tokens(key) -> set[str]:
    from pynput.keyboard import Key

    if isinstance(key, Key):
        name = key.name
        if name == "alt_gr":
            return {"alt_gr", "alt", "alt_r"}
        if name.endswith(("_l", "_r")):
            return {name, name[:-2]}
        return {name}
    vk = getattr(key, "vk", None)
    if vk is not None and 0x30 <= vk <= 0x39:
        return {str(vk - 0x30)}
    ch = getattr(key, "char", None)
    if ch:
        return {ch.lower()}
    return {f"vk{vk}"}


class GlobalHotkey:
    def __init__(self, machine: HotkeyMachine):
        self.machine = machine
        self.listener = None

    def start(self) -> None:
        from pynput import keyboard

        m = self.machine
        if sys.platform == "win32":
            def win32_filter(msg, data):
                if data.flags & 0x10:  # injected (e.g. our own Ctrl+V)
                    return False
                tokens = win_vk_tokens(data.vkCode)
                if msg in (0x100, 0x104):
                    swallow = m.down(tokens)
                elif msg in (0x101, 0x105):
                    swallow = m.up(tokens)
                else:
                    return False
                if swallow:
                    self.listener.suppress_event()
                return False  # handled here; skip the on_press callbacks

            self.listener = keyboard.Listener(win32_event_filter=win32_filter)
        else:
            self.listener = keyboard.Listener(
                on_press=lambda k: m.down(pynput_tokens(k)) and None,
                on_release=lambda k: m.up(pynput_tokens(k)) and None,
            )
        self.listener.daemon = True
        self.listener.start()

    def stop(self) -> None:
        if self.listener:
            self.listener.stop()
            self.listener = None

    def wait_released(self, timeout: float = 1.5) -> None:
        """Wait until the user lets go of the hotkey before pasting, so the
        paste isn't turned into Ctrl+Win+V."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not (self.machine.held & (self.machine.combo | {"ctrl", "cmd", "alt", "shift"})):
                return
            time.sleep(0.02)
