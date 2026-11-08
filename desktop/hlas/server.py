"""Local HTTP API so any project (any language) can use Hlas.

    hlas serve                      # http://127.0.0.1:8765

    POST /transcribe?language=auto&cleanup=1&coding=0
         body: raw audio (wav/mp3/m4a/webm/ogg) or multipart form with a "file" field
         -> {"text": ..., "raw": ..., "languages": [...], ...}
    POST /cleanup     body: {"text": "...", "coding": false} -> {"text": ...}
    GET  /health      -> {"ok": true}

Listens on localhost only by default. Set a token (--token or HLAS_TOKEN) to
require "Authorization: Bearer <token>".
"""

from __future__ import annotations

import json
import os
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import cleanup
from .config import LANGS, Config
from .pipeline import Transcriber
from .stt import SttError

MAX_BODY = 100 * 1024 * 1024


def _truthy(v: str | None, default: bool | None) -> bool | None:
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")


def parse_multipart(content_type: str, body: bytes) -> tuple[bytes, str, str] | None:
    msg = BytesParser(policy=email_policy).parsebytes(
        f"Content-Type: {content_type}\r\n\r\n".encode() + body
    )
    for part in msg.iter_parts():
        if part.get_param("name", header="content-disposition") == "file":
            return (part.get_payload(decode=True) or b"", part.get_filename() or "audio",
                    part.get_content_type())
    return None


def make_handler(transcriber: Transcriber, token: str | None, cors: bool):
    class Handler(BaseHTTPRequestHandler):
        server_version = "hlas"

        def log_message(self, fmt, *args):  # quieter log
            print(f"[hlas] {self.address_string()} {fmt % args}")

        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            if cors:
                self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            if cors:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.end_headers()

        def _authorized(self) -> bool:
            if not token:
                return True
            if self.headers.get("Authorization", "") == f"Bearer {token}":
                return True
            self._send(401, {"error": "unauthorized"})
            return False

        def do_GET(self):
            if urlparse(self.path).path == "/health":
                self._send(200, {"ok": True, "provider": transcriber.cfg.stt_provider})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._authorized():
                return
            url = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(url.query).items()}
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                self._send(400, {"error": "empty or too large body"})
                return
            body = self.rfile.read(length)
            ctype = self.headers.get("Content-Type", "application/octet-stream")
            try:
                if url.path == "/transcribe":
                    lang = q.get("language", "auto")
                    if lang not in LANGS:
                        self._send(400, {"error": f"language must be one of {LANGS}"})
                        return
                    filename, mime = "audio", ctype
                    if ctype.startswith("multipart/form-data"):
                        part = parse_multipart(ctype, body)
                        if part is None:
                            self._send(400, {"error": 'multipart needs a "file" field'})
                            return
                        body, filename, mime = part
                    result = transcriber.transcribe_bytes(
                        body, filename, mime, lang, _truthy(q.get("cleanup"), None),
                        bool(_truthy(q.get("coding"), False)))
                    self._send(200, result.to_dict())
                elif url.path == "/cleanup":
                    data = json.loads(body.decode("utf-8"))
                    text, warning = cleanup.clean(str(data.get("text", "")), transcriber.cfg,
                                                  coding=bool(data.get("coding")))
                    self._send(200, {"text": text, "warning": warning})
                else:
                    self._send(404, {"error": "not found"})
            except SttError as e:
                self._send(502, {"error": str(e)})
            except (ValueError, json.JSONDecodeError) as e:
                self._send(400, {"error": str(e)})

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8765, token: str | None = None, cors: bool = False,
          cfg: Config | None = None) -> None:
    token = token or os.environ.get("HLAS_TOKEN") or None
    if host not in ("127.0.0.1", "localhost", "::1") and not token:
        raise SystemExit("Refusing to listen on a non-local address without --token.")
    transcriber = Transcriber(cfg)
    httpd = ThreadingHTTPServer((host, port), make_handler(transcriber, token, cors))
    print(f"[hlas] listening on http://{host}:{port}  (provider: {transcriber.cfg.stt_provider})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
