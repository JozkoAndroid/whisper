# Hlas

Push-to-talk dictation for **Slovak, German and English**, including switching languages mid-sentence. You hold a key, talk, let go, and the text is pasted into whatever app you're in. An optional Claude pass fixes misheard words, punctuation, filler words and spoken self-corrections. It never translates.

What's here:

| Part | What it is |
|---|---|
| `desktop/` | Windows app (also runs on Linux/macOS): tray icon, global hotkey, a small recording indicator. It's also a Python library, a CLI and a local HTTP API, so other projects can use it. |
| `android/` | Android voice keyboard (an IME) that works in any app. |

## How the accuracy works

1. **Speech to text**, `gpt-transcribe` (OpenAI) by default. It takes a *list* of expected languages (`sk`, `de`, `en`), which handles mixed sentences better than Whisper. Whisper detects one language per 30 seconds and often hears Slovak as Czech. Alternatives: ElevenLabs Scribe v2 (strong on European languages) and Groq Whisper large-v3 (fastest, weakest at mixing). On desktop there's also an offline faster-whisper mode.
2. **Your vocabulary** (names, jargon, product terms) is sent to the speech model as keywords and to the cleanup model as exact spellings. This is the cheapest accuracy gain there is, so fill it in.
3. **Cleanup** (optional, needs an Anthropic key): fixes diacritics, misheard words, punctuation and fillers (ehm, äh, um, akože), and applies corrections like *"o piatej, nie, o šiestej"* -> *"o šiestej"*. In editors and terminals it switches to a coding style that spells technical terms correctly. If cleanup fails, times out or returns something odd, you get the raw transcript, so a dictation is never lost.
4. **Silence handling**: leading and trailing silence is trimmed, and silent recordings are skipped. That prevents the classic "Thanks for watching" hallucination and shortens uploads.

Honest caveat: no vendor publishes independent Slovak code-switching benchmarks. Before relying on the default, record 10 typical dictations of your own and try them with `hlas transcribe file.wav --json` on each provider.

## Windows

1. Download `Hlas.exe` from the latest GitHub Actions run (artifact `Hlas-windows`) or from a release. To run from source instead: `pip install "./desktop[app]"`, then `hlas`.
2. Start it. The settings window opens. Paste your **OpenAI API key** (speech) and optionally your **Anthropic API key** (cleanup). Save.
3. Click into any text field, then:

| Keys | Action |
|---|---|
| hold **Ctrl+Win** | record; release to transcribe and paste |
| **Ctrl+Win+Space** | hands-free; tap Ctrl+Win again to stop |
| while recording: **Ctrl+Win + 1 / 2 / 3 / 0** | from this point on: Slovak / German / English / auto |
| **Esc** | cancel |

Auto mode already handles mixed sentences. The language keys are for when you know the next part is one language and want to force it: each part gets transcribed with its own language.

In the tray menu you can set the language, turn cleanup on or off, copy the last dictation and toggle "Start with Windows". Every dictation is saved to `%APPDATA%\Hlas\history.jsonl`, so nothing is lost if a paste lands in the wrong place.

## Android

1. Install `Hlas-android.apk` (artifact `Hlas-android`; allow "install unknown apps").
2. Open **Hlas** and tap: 1. Allow microphone, 2. Enable Hlas keyboard, 3. Switch to Hlas keyboard. Enter your keys and save.
3. In any app, switch to the Hlas keyboard. **Tap** the mic to talk hands-free and tap again to finish, or **hold** it and release. Tap the language chip while you talk to switch language from that point on. **ABC** goes back to your normal keyboard (long-press it to pick one).

Note: CI signs the APK with a throwaway debug key. To install a newer build over an old one, uninstall the old one first, or sign the build with your own keystore.

## Using it from other projects

**Python library**

```python
from hlas import Transcriber            # pip install ./desktop
result = Transcriber().transcribe_file("memo.m4a")   # wav, mp3, m4a, webm, ogg
print(result.text, result.raw, result.languages)
```

**CLI**

```bash
hlas transcribe memo.wav                 # prints the text
hlas transcribe memo.wav --language de --no-cleanup --json
hlas listen --coding                     # record from the mic until Enter, print the text
hlas listen | xclip -selection clipboard # e.g. pipe it anywhere
hlas config set stt_provider elevenlabs
hlas config set vocabulary "Kubernetes,Žilina,Hlas"
```

**HTTP API** (any language, including browser apps)

```bash
hlas serve                    # http://127.0.0.1:8765, localhost only
hlas serve --cors --token s3cret

curl -X POST "http://127.0.0.1:8765/transcribe?language=auto&cleanup=1" \
     -H "Content-Type: audio/wav" --data-binary @memo.wav
# -> {"text": "...", "raw": "...", "languages": ["sk","de"], "seconds_stt": 0.9, ...}

curl -X POST http://127.0.0.1:8765/cleanup -d '{"text": "ehm ahoj ako sa mas"}'
```

```js
// Browser: record with MediaRecorder, then
const res = await fetch("http://127.0.0.1:8765/transcribe", {
  method: "POST", headers: { "Content-Type": "audio/webm" }, body: blob });
const { text } = await res.json();
```

**While coding:** the desktop hotkey works in VS Code, Cursor, JetBrains IDEs, Windows Terminal and Claude Code, so you can dictate prompts and comments directly. Cleanup automatically switches to the coding style there.

## Settings

All settings are in the settings window, or in `%APPDATA%\Hlas\config.json` (`~/.config/hlas/config.json` on Linux). API keys can also come from the environment variables `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `GROQ_API_KEY` and `ANTHROPIC_API_KEY`.

| Setting | Default | Notes |
|---|---|---|
| `stt_provider` | `openai` | `openai`, `elevenlabs`, `groq`, `local` |
| `language` | `auto` | `auto` means SK/DE/EN with mixing |
| `vocabulary` | `[]` | names and jargon; matters a lot |
| `cleanup` | `true` | needs `anthropic_api_key` |
| `cleanup_model` | `claude-opus-5-5` | `claude-haiku-5-5` is much faster and cheaper, slightly less careful |
| `cleanup_effort` | `low` | low keeps latency down |
| `hotkey` | `ctrl+cmd` | `cmd` = Win key; e.g. `ctrl+alt`, `f9`, `ctrl_r` |
| `context_aware` | `true` | coding style in IDEs and terminals (Windows) |

Keys are stored in plain text in your user profile (desktop) or in the app's private storage (Android). They never go anywhere except the provider you picked.

## Development

```bash
cd desktop && pip install -e ".[app,dev]" && pytest          # 28 tests
cd android && ./gradlew testDebugUnitTest assembleDebug        # needs the Android SDK
```

CI (`.github/workflows/build.yml`) runs the tests and builds `Hlas.exe` and the APK on every push. Pushing a `v*` tag creates a release with both.

The cleanup prompt exists twice, in `desktop/hlas/cleanup.py` and `android/.../Cleanup.kt`. Keep the two in sync.
