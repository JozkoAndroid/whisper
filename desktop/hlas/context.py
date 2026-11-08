"""Which app is in front? Used to switch the cleanup to a coding style in
editors and terminals (Windows only; elsewhere returns "")."""

from __future__ import annotations

import sys

CODING_APPS = {
    "code.exe", "code - insiders.exe", "cursor.exe", "windsurf.exe", "zed.exe",
    "windowsterminal.exe", "wt.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "conhost.exe",
    "wezterm-gui.exe", "alacritty.exe", "mintty.exe", "tabby.exe", "warp.exe",
    "idea64.exe", "pycharm64.exe", "webstorm64.exe", "clion64.exe", "goland64.exe",
    "rider64.exe", "phpstorm64.exe", "rustrover64.exe", "datagrip64.exe", "studio64.exe",
    "devenv.exe", "sublime_text.exe", "notepad++.exe", "nvim-qt.exe", "gvim.exe",
    "claude.exe",
}


def foreground_app() -> str:
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value.replace("/", "\\").rsplit("\\", 1)[-1].lower()
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        pass
    return ""


def is_coding_app(name: str) -> bool:
    return name in CODING_APPS
