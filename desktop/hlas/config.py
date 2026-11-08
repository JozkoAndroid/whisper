"""Settings, stored as JSON in the user's config folder.

Windows: %APPDATA%\\Hlas\\config.json
macOS:   ~/Library/Application Support/Hlas/config.json
Linux:   ~/.config/hlas/config.json

API keys can also come from environment variables (OPENAI_API_KEY,
ELEVENLABS_API_KEY, GROQ_API_KEY, ANTHROPIC_API_KEY); a key saved in the
config file wins over the environment.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

LANGS = ("auto", "sk", "de", "en")
STT_PROVIDERS = ("local", "groq", "openai", "elevenlabs")
CLEANUP_PROVIDERS = ("auto", "groq", "ollama", "claude")

ENV_KEYS = {
    "openai_api_key": "OPENAI_API_KEY",
    "elevenlabs_api_key": "ELEVENLABS_API_KEY",
    "groq_api_key": "GROQ_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
}


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "Hlas"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Hlas"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hlas"


@dataclass
class Config:
    # Speech to text. "local" = free offline models (default), "groq" = free
    # tier online, "openai"/"elevenlabs" = paid.
    stt_provider: str = "local"
    openai_model: str = "gpt-transcribe"
    elevenlabs_model: str = "scribe_v2"
    groq_model: str = "whisper-large-v3"
    language: str = "auto"  # auto = Slovak/German/English, mixing allowed
    languages: list[str] = field(default_factory=lambda: ["sk", "de", "en"])
    vocabulary: list[str] = field(default_factory=list)  # names, jargon, product terms

    # Cleanup pass. Optional: without a provider the raw transcript is used.
    cleanup: bool = True
    cleanup_provider: str = "auto"  # auto, groq, ollama, claude
    groq_cleanup_model: str = ""  # empty = pick the best model Groq offers
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "gemma3:12b"
    cleanup_model: str = "claude-opus-5-5"  # only for cleanup_provider = claude (paid)
    cleanup_effort: str = "low"
    context_aware: bool = True  # coding style in IDEs/terminals (Windows only)

    # Keys
    openai_api_key: str = ""
    elevenlabs_api_key: str = ""
    groq_api_key: str = ""
    anthropic_api_key: str = ""

    # Desktop app
    hotkey: str = "ctrl+cmd"  # hold to talk; add Space while holding to lock hands-free
    paste: bool = True  # paste into the focused window (else only copy)
    restore_clipboard: bool = True
    sounds: bool = True
    microphone: str = ""  # empty = system default
    max_seconds: int = 1800  # hard stop for a single recording

    def key(self, name: str) -> str:
        """API key from config, falling back to the environment."""
        value = getattr(self, name, "") or ""
        return value or os.environ.get(ENV_KEYS[name], "")

    @classmethod
    def path(cls) -> Path:
        return config_dir() / "config.json"

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or cls.path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        known = {f.name for f in fields(cls)}
        cfg = cls(**{k: v for k, v in data.items() if k in known})
        cfg.validate()
        return cfg

    def save(self, path: Path | None = None) -> Path:
        path = path or self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return path

    def validate(self) -> None:
        if self.language not in LANGS:
            self.language = "auto"
        if self.stt_provider not in STT_PROVIDERS:
            self.stt_provider = "local"
        if self.cleanup_provider not in CLEANUP_PROVIDERS:
            self.cleanup_provider = "auto"
        self.languages = [l for l in self.languages if l in LANGS[1:]] or ["sk", "de", "en"]
        self.vocabulary = [v.strip() for v in self.vocabulary if v and v.strip()]
