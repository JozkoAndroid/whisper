"""The desktop app: tray icon, recording pill, settings window.

Runs on Windows (main target), Linux (X11) and macOS. The Tk main loop owns
the main thread; the hotkey listener, the tray icon and transcription run in
background threads and talk to the UI through a queue.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from . import audio, stt
from .config import LANGS, STT_PROVIDERS, Config, config_dir
from .context import foreground_app, is_coding_app
from .hotkey import GlobalHotkey, HotkeyMachine, parse_combo
from .insert import paste_text
from .pipeline import Transcriber

LANG_LABEL = {"auto": "SK·DE·EN", "sk": "SK", "de": "DE", "en": "EN"}
BG, FG, RED, DIM, AMBER = "#16161a", "#f4f4f5", "#ef4444", "#a1a1aa", "#f59e0b"


# --- small platform helpers -------------------------------------------------

def beep(kind: str) -> None:
    if sys.platform != "win32":
        return

    def _b():
        try:
            import winsound

            if kind == "start":
                winsound.Beep(988, 45)
            elif kind == "stop":
                winsound.Beep(740, 45)
            else:
                winsound.Beep(330, 120)
        except Exception:
            pass

    threading.Thread(target=_b, daemon=True).start()


def single_instance() -> bool:
    if sys.platform != "win32":
        return True
    import ctypes

    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\HlasDictationMutex")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def make_no_activate(win: tk.Toplevel) -> None:
    """Windows: the pill must never take focus, or the paste lands in it."""
    if sys.platform != "win32":
        return
    import ctypes

    win.update_idletasks()
    hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
    GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST = -20, 0x08000000, 0x80, 0x8
    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
    win._hwnd = hwnd  # type: ignore[attr-defined]


def show_no_activate(win: tk.Toplevel) -> None:
    if sys.platform == "win32" and getattr(win, "_hwnd", None):
        import ctypes

        ctypes.windll.user32.ShowWindow(win._hwnd, 4)  # SW_SHOWNOACTIVATE
        ctypes.windll.user32.SetWindowPos(win._hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
    else:
        win.deiconify()
        win.lift()


def set_autostart(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    import winreg

    exe = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" -m hlas'
    if getattr(sys, "frozen", False):
        exe = f'"{exe}"'
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                         winreg.KEY_SET_VALUE)
    try:
        if enabled:
            winreg.SetValueEx(key, "Hlas", 0, winreg.REG_SZ, exe)
        else:
            try:
                winreg.DeleteValue(key, "Hlas")
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def autostart_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run")
        winreg.QueryValueEx(key, "Hlas")
        winreg.CloseKey(key)
        return True
    except OSError:
        return False


# --- history ----------------------------------------------------------------

def history_path():
    return config_dir() / "history.jsonl"


def save_history(entry: dict) -> None:
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def trim_history(keep: int = 1000) -> None:
    path = history_path()
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) > keep:
        path.write_text("\n".join(lines[-keep:]) + "\n", encoding="utf-8")


# --- the app ----------------------------------------------------------------

class App:
    def __init__(self):
        self.cfg = Config.load()
        self.transcriber = Transcriber(self.cfg)
        self.recorder = audio.Recorder(self.cfg.microphone or None)
        self.events: queue.Queue = queue.Queue()
        self.lang = self.cfg.language
        self.last_text = ""
        self.busy = 0
        self.coding = False
        self.tray = None

        if sys.platform == "win32":
            try:  # crisp text on high-DPI screens
                import ctypes

                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass
        self.root = tk.Tk()
        self.root.withdraw()
        self.scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        self.root.title("Hlas")
        self._build_pill()

        self.machine = HotkeyMachine(
            parse_combo(self.cfg.hotkey),
            on_start=lambda: self.events.put(("start",)),
            on_stop=lambda: self.events.put(("stop",)),
            on_cancel=lambda: self.events.put(("cancel",)),
            on_lang=lambda l: self.events.put(("lang", l)),
            on_lock=lambda: self.events.put(("lock",)),
        )
        self.hotkey = GlobalHotkey(self.machine)
        self.locked = False

    # pill ---------------------------------------------------------------

    def _build_pill(self) -> None:
        pill = tk.Toplevel(self.root)
        pill.overrideredirect(True)
        pill.attributes("-topmost", True)
        try:
            pill.attributes("-alpha", 0.94)
        except tk.TclError:
            pass
        pill.configure(bg=BG)
        k = self.scale
        self.pw, self.ph = int(300 * k), int(40 * k)
        self.canvas = tk.Canvas(pill, width=self.pw, height=self.ph, bg=BG, highlightthickness=0)
        self.canvas.pack()
        self.dot = self.canvas.create_oval(14 * k, 14 * k, 26 * k, 26 * k, fill=RED, outline="")
        self.label = self.canvas.create_text(38 * k, 20 * k, anchor="w", fill=FG, font=("Segoe UI", 11, "bold"),
                                             text="")
        self.sub = self.canvas.create_text(288 * k, 20 * k, anchor="e", fill=DIM, font=("Segoe UI", 10), text="")
        pill.withdraw()
        self.pill = pill
        make_no_activate(pill)
        self.root.update_idletasks()
        sw, sh = pill.winfo_screenwidth(), pill.winfo_screenheight()
        pill.geometry(f"{self.pw}x{self.ph}+{(sw - self.pw) // 2}+{sh - int(120 * self.scale)}")
        self._hide_at = 0.0

    def pill_show(self, text: str, sub: str = "", color: str = RED, hide_after: float = 0) -> None:
        self.canvas.itemconfigure(self.label, text=text)
        self.canvas.itemconfigure(self.sub, text=sub)
        self.canvas.itemconfigure(self.dot, fill=color)
        show_no_activate(self.pill)
        self._hide_at = time.monotonic() + hide_after if hide_after else 0.0

    def pill_hide(self) -> None:
        if sys.platform == "win32" and getattr(self.pill, "_hwnd", None):
            import ctypes

            ctypes.windll.user32.ShowWindow(self.pill._hwnd, 0)  # SW_HIDE
        else:
            self.pill.withdraw()

    # events -------------------------------------------------------------

    def run(self) -> None:
        if not single_instance():
            messagebox.showinfo("Hlas", "Hlas is already running (see the tray icon).")
            return
        trim_history()
        self.hotkey.start()
        self._start_tray()
        self.root.after(30, self._tick)
        if not self._has_stt_key():
            self.root.after(300, self.open_settings)
        self.root.mainloop()

    def _has_stt_key(self) -> bool:
        p = self.cfg.stt_provider
        return p == "local" or bool(self.cfg.key(f"{p}_api_key"))

    def _tick(self) -> None:
        try:
            while True:
                self._handle(*self.events.get_nowait())
        except queue.Empty:
            pass
        if self.recorder.recording:
            secs = self.recorder.seconds
            k = self.scale
            r = (5 + 4 * self.recorder.level) * k
            self.canvas.coords(self.dot, 20 * k - r, 20 * k - r, 20 * k + r, 20 * k + r)
            mode = "  locked" if self.locked else ""
            self.canvas.itemconfigure(self.label, text=f"{LANG_LABEL[self.lang]}{mode}")
            self.canvas.itemconfigure(self.sub, text=f"{int(secs // 60)}:{int(secs % 60):02d}")
            if secs >= self.cfg.max_seconds:
                self._handle("stop")
        elif self._hide_at and time.monotonic() > self._hide_at:
            self._hide_at = 0.0
            if not self.busy:
                self.pill_hide()
        self.root.after(30, self._tick)

    def _handle(self, kind: str, *args) -> None:
        if kind == "ui":
            args[0]()
        elif kind == "start":
            if self.recorder.recording:
                return
            if not self._has_stt_key():
                self.pill_show("Add an API key", "tray > Settings", AMBER, hide_after=3)
                self.machine.reset()
                return
            self.coding = self.cfg.context_aware and is_coding_app(foreground_app())
            try:
                self.recorder.start(self.lang)
            except Exception as e:
                self.machine.reset()
                self.pill_show("Microphone error", str(e)[:28], AMBER, hide_after=4)
                return
            self.locked = False
            if self.cfg.sounds:
                beep("start")
            self.pill_show(LANG_LABEL[self.lang], "0:00", RED)
            threading.Thread(target=stt.warm_up, args=(self.cfg,), daemon=True).start()
        elif kind == "lock":
            self.locked = True
        elif kind == "lang":
            self.lang = args[0]
            if self.recorder.recording:
                self.recorder.mark(self.lang)
            self._refresh_tray()
        elif kind == "cancel":
            if self.recorder.recording:
                self.recorder.stop()
                self.pill_show("Cancelled", "", DIM, hide_after=0.8)
        elif kind == "stop":
            if not self.recorder.recording:
                return
            segments = self.recorder.stop()
            if self.cfg.sounds:
                beep("stop")
            seconds = sum(len(s) for s, _ in segments) / audio.SAMPLE_RATE
            if seconds < 0.3:
                self.pill_hide()
                return
            self.busy += 1
            k = self.scale
            self.canvas.coords(self.dot, 14 * k, 14 * k, 26 * k, 26 * k)
            self.pill_show("Transcribing", "", AMBER)
            threading.Thread(target=self._process, args=(segments, self.coding), daemon=True).start()
        elif kind == "done":
            self.busy -= 1
            text, warning = args
            if warning:
                self.pill_show(warning[:36], "", AMBER, hide_after=2.5)
            elif text:
                self.pill_hide()
            else:
                self.pill_show("No speech", "", DIM, hide_after=1.2)
        elif kind == "error":
            self.busy -= 1
            if self.cfg.sounds:
                beep("error")
            self.pill_show(args[0][:36], "", AMBER, hide_after=4)

    def _process(self, segments, coding: bool) -> None:
        try:
            result = self.transcriber.transcribe_segments(segments, coding=coding)
        except Exception as e:  # SttError and anything unexpected
            self.events.put(("error", str(e)))
            return
        if result.text:
            self.last_text = result.text
            save_history({"time": time.strftime("%Y-%m-%d %H:%M:%S"), **result.to_dict()})
            self.hotkey.wait_released()
            try:
                paste_text(result.text + " ", restore=self.cfg.restore_clipboard, paste=self.cfg.paste)
            except Exception as e:
                self.events.put(("error", f"Paste failed: {e}"))
                return
        self.events.put(("done", result.text, result.warning))

    # tray -----------------------------------------------------------------

    def _icon_image(self):
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((2, 2, 62, 62), fill=(22, 22, 26, 255))
        d.rounded_rectangle((24, 12, 40, 38), radius=8, fill=(239, 68, 68, 255))
        d.arc((17, 22, 47, 46), start=0, end=180, fill=(244, 244, 245, 255), width=3)
        d.line((32, 46, 32, 53), fill=(244, 244, 245, 255), width=3)
        return img

    def _start_tray(self) -> None:
        try:
            import pystray
        except Exception:
            return
        item = pystray.MenuItem

        def ui(fn):  # tray callbacks run on the tray thread; hand Tk work to the main loop
            return lambda *a: self.events.put(("ui", fn))

        def set_lang(code):
            return lambda *a: self.events.put(("lang", code))

        lang_items = [item(LANG_LABEL[c] if c != "auto" else "Auto (mixed)", set_lang(c),
                           checked=lambda i, c=c: self.lang == c, radio=True) for c in LANGS]
        menu = pystray.Menu(
            item("Settings", ui(self.open_settings), default=True),
            item("Language", pystray.Menu(*lang_items)),
            item("AI cleanup", lambda *a: self._toggle_cleanup(), checked=lambda i: self.cfg.cleanup),
            item("Copy last dictation", lambda *a: self._copy_last()),
            item("Start with Windows", lambda *a: self._toggle_autostart(),
                 checked=lambda i: autostart_enabled(), visible=sys.platform == "win32"),
            pystray.Menu.SEPARATOR,
            item("Quit", ui(self.quit)),
        )
        self.tray = pystray.Icon("hlas", self._icon_image(), "Hlas dictation", menu)
        try:
            self.tray.run_detached()
        except Exception:
            self.tray = None

    def _refresh_tray(self) -> None:
        if self.tray:
            try:
                self.tray.update_menu()
            except Exception:
                pass

    def _toggle_cleanup(self) -> None:
        self.cfg.cleanup = not self.cfg.cleanup
        self.cfg.save()
        self._refresh_tray()

    def _toggle_autostart(self) -> None:
        try:
            set_autostart(not autostart_enabled())
        except OSError:
            pass
        self._refresh_tray()

    def _copy_last(self) -> None:
        if self.last_text:
            import pyperclip

            pyperclip.copy(self.last_text)

    def quit(self) -> None:
        self.hotkey.stop()
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    # settings ---------------------------------------------------------------

    def open_settings(self) -> None:
        if getattr(self, "_settings", None) and self._settings.winfo_exists():
            self._settings.lift()
            self._settings.focus_force()
            return
        cfg = self.cfg
        win = tk.Toplevel(self.root)
        win.title("Hlas settings")
        win.resizable(False, False)
        self._settings = win
        frm = ttk.Frame(win, padding=16)
        frm.pack(fill="both", expand=True)
        v: dict[str, tk.Variable] = {}
        row = 0

        def add(label, widget, hint=""):
            nonlocal row
            ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
            widget.grid(row=row, column=1, sticky="ew", pady=4)
            if hint:
                ttk.Label(frm, text=hint, foreground="#71717a").grid(row=row, column=2, sticky="w", padx=(8, 0))
            row += 1

        def entry(name, show=None, width=44):
            v[name] = tk.StringVar(value=str(getattr(cfg, name)))
            return ttk.Entry(frm, textvariable=v[name], show=show or "", width=width)

        def combo(name, values):
            v[name] = tk.StringVar(value=str(getattr(cfg, name)))
            return ttk.Combobox(frm, textvariable=v[name], values=list(values), state="readonly", width=42)

        def check(name, text):
            v[name] = tk.BooleanVar(value=bool(getattr(cfg, name)))
            return ttk.Checkbutton(frm, text=text, variable=v[name])

        add("Speech model", combo("stt_provider", STT_PROVIDERS), "openai = most accurate for mixing")
        add("OpenAI API key", entry("openai_api_key", "*"))
        add("ElevenLabs API key", entry("elevenlabs_api_key", "*"), "optional")
        add("Groq API key", entry("groq_api_key", "*"), "optional")
        add("Default language", combo("language", LANGS), "auto = SK/DE/EN mixed")
        ttk.Separator(frm).grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)
        row += 1
        add("AI cleanup", check("cleanup", "Fix mistakes, punctuation and filler words"))
        add("Anthropic API key", entry("anthropic_api_key", "*"), "for cleanup")
        add("Cleanup model", ttk.Combobox(frm, textvariable=v.setdefault("cleanup_model", tk.StringVar(
            value=cfg.cleanup_model)), values=["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"],
            width=42), "haiku = fastest")
        add("Coding style in IDEs", check("context_aware", "Detect editors and terminals"))
        ttk.Separator(frm).grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)
        row += 1
        add("Hotkey (hold)", entry("hotkey"), "e.g. ctrl+cmd, ctrl+alt, f9")
        add("Paste into app", check("paste", "Paste automatically (else copy only)"))
        add("Sounds", check("sounds", "Beep on start/stop"))

        ttk.Label(frm, text="Vocabulary (one per line: names, jargon, products)").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(10, 2))
        row += 1
        vocab = tk.Text(frm, width=60, height=6, font=("Segoe UI", 10))
        vocab.insert("1.0", "\n".join(cfg.vocabulary))
        vocab.grid(row=row, column=0, columnspan=3, sticky="ew")
        row += 1
        help_text = ("Hold the hotkey and talk, release to paste.  Hotkey + Space = hands-free, "
                     "tap hotkey to stop.\nWhile recording: hotkey + 1 SK, 2 DE, 3 EN, 0 auto.  Esc cancels.")
        ttk.Label(frm, text=help_text, foreground="#52525b", justify="left").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(10, 0))
        row += 1

        def save():
            for name, var in v.items():
                setattr(cfg, name, var.get())
            cfg.vocabulary = [l.strip() for l in vocab.get("1.0", "end").splitlines() if l.strip()]
            cfg.validate()
            cfg.save()
            self.lang = cfg.language
            self.machine.combo = set(parse_combo(cfg.hotkey))
            self.machine.reset()
            self._refresh_tray()
            win.destroy()

        btns = ttk.Frame(frm)
        btns.grid(row=row, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Save", command=save).pack(side="right", padx=8)
        win.lift()
        win.focus_force()


def main() -> None:
    App().run()


if __name__ == "__main__":
    main()
