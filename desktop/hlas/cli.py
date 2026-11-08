"""Command line:

    hlas                         start the desktop app (tray + hotkey)
    hlas transcribe FILE         print the text of an audio file
    hlas listen                  record from the mic until Enter, print the text
    hlas serve                   local HTTP API for other projects
    hlas models                  download the free offline speech models (1.3 GB, once)
    hlas config                  show settings file path and values (keys hidden)
    hlas config set KEY VALUE    change a setting, e.g. hlas config set stt_provider elevenlabs
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, fields

from .config import LANGS, Config


def _print_result(result, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        if result.warning:
            print(f"[hlas] {result.warning}", file=sys.stderr)
        print(result.text)


def cmd_transcribe(a) -> int:
    from .pipeline import Transcriber

    result = Transcriber().transcribe_file(a.file, a.language, False if a.no_cleanup else None, a.coding)
    _print_result(result, a.json)
    return 0


def cmd_listen(a) -> int:
    from .audio import Recorder
    from .pipeline import Transcriber

    cfg = Config.load()
    t = Transcriber(cfg)
    rec = Recorder(cfg.microphone or None)
    rec.start(a.language or cfg.language)
    print("[hlas] recording... press Enter to stop", file=sys.stderr)
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass
    segments = rec.stop()
    print("[hlas] transcribing...", file=sys.stderr)
    result = t.transcribe_segments(segments, False if a.no_cleanup else None, a.coding)
    _print_result(result, a.json)
    return 0


def cmd_serve(a) -> int:
    from .server import serve

    serve(a.host, a.port, a.token, a.cors)
    return 0


def cmd_models(a) -> int:
    from . import local

    local.download_cli()
    return 0


def cmd_config(a) -> int:
    cfg = Config.load()
    if a.action == "set":
        names = {f.name: f for f in fields(Config)}
        if a.key not in names:
            print(f"unknown setting {a.key!r}; known: {', '.join(names)}", file=sys.stderr)
            return 2
        current = getattr(cfg, a.key)
        value: object = a.value
        if isinstance(current, bool):
            value = a.value.lower() in ("1", "true", "yes", "on")
        elif isinstance(current, int):
            value = int(a.value)
        elif isinstance(current, list):
            value = [x.strip() for x in a.value.split(",") if x.strip()]
        setattr(cfg, a.key, value)
        cfg.validate()
        print(f"saved {cfg.save()}")
        return 0
    data = asdict(cfg)
    for k in list(data):
        if k.endswith("_api_key"):
            data[k] = "set" if cfg.key(k) else ""
    print(f"# {Config.path()}")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hlas", description="Dictation for Slovak, German and English.")
    sub = p.add_subparsers(dest="cmd")

    def common(sp):
        sp.add_argument("--language", "-l", choices=LANGS, default=None)
        sp.add_argument("--no-cleanup", action="store_true", help="skip the AI cleanup pass")
        sp.add_argument("--coding", action="store_true", help="coding style cleanup")
        sp.add_argument("--json", action="store_true", help="print the full result as JSON")

    sp = sub.add_parser("transcribe", help="transcribe an audio file")
    sp.add_argument("file")
    common(sp)
    sp.set_defaults(fn=cmd_transcribe)

    sp = sub.add_parser("listen", help="record from the microphone until Enter")
    common(sp)
    sp.set_defaults(fn=cmd_listen)

    sp = sub.add_parser("serve", help="local HTTP API")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--token", default=None)
    sp.add_argument("--cors", action="store_true", help="allow browser pages to call the API")
    sp.set_defaults(fn=cmd_serve)

    sp = sub.add_parser("models", help="download the offline speech models")
    sp.set_defaults(fn=cmd_models)

    sp = sub.add_parser("config", help="show or change settings")
    sp.add_argument("action", nargs="?", choices=["show", "set"], default="show")
    sp.add_argument("key", nargs="?")
    sp.add_argument("value", nargs="?")
    sp.set_defaults(fn=cmd_config)

    sub.add_parser("app", help="desktop app (default)")
    a = p.parse_args(argv)
    if a.cmd in (None, "app"):
        from .app import main as app_main

        app_main()
        return 0
    if a.cmd == "config" and a.action == "set" and (a.key is None or a.value is None):
        p.error("usage: hlas config set KEY VALUE")
    from .stt import SttError

    try:
        return a.fn(a)
    except SttError as e:
        print(f"[hlas] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
