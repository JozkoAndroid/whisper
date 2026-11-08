# Hlas

Free push-to-talk dictation for **Slovak, German and English**, including switching between them. You hold a key, talk, let go, and the text is typed into whatever app you're in.

- `desktop/`: Windows app (also Linux/macOS). It's also a Python library, a CLI and a local HTTP API for your other projects.
- `android/`: an Android voice keyboard that works in any app.

## It's free

By default everything runs **offline on your own device**. There are no accounts, no API keys and no costs, and your voice never leaves your device. The only cost is a one-time 1.3 GB model download.

| Part | What it uses | Cost |
|---|---|---|
| Speech to text | Two open models, offline (below) | free |
| Text cleanup (optional) | Groq's free tier (needs a free account), or Ollama on your PC | free |
| Paid extras (optional, off) | OpenAI / ElevenLabs speech, Claude cleanup | paid, only if you add their keys |

Claude is **not** used unless you choose it yourself and enter a paid Anthropic API key.

## How the accuracy works

There's no single open model that is good at all three languages, so Hlas runs two:

- **NVIDIA Parakeet TDT 0.6B v3**: excellent English and German, but it often writes Slovak as Polish.
- **KInIT's Slovak fine-tune** of the same model: on real Slovak speech it makes about 4x fewer errors (6.6% vs 24.3% word error rate in KInIT's tests). It can't do English or German anymore.

Your recording is cut into phrases at pauses. **Both models transcribe every phrase**, and Hlas keeps the result that reads like real text: Slovak from the Slovak model, English or German from the other. Both models are fast on an ordinary CPU, about 10x faster than real time on a laptop.

I also checked the other open options:
- Whisper large-v3 is more accurate on Slovak than base Parakeet (16% error), but still well behind the Slovak fine-tune, and too slow on a normal CPU.
- Newer models (Cohere Transcribe, Qwen3-ASR, Voxtral) don't support Slovak.
- Groq's online Whisper is also selectable.

**Limits:** switching language **mid-phrase without a pause** (for example *"pošli mi ten report as soon as possible"* said in one breath) usually comes out in one language. Pause briefly between languages, or press the language key (below). The optional cleanup step also fixes punctuation, filler words, names and spoken corrections.

## Windows

1. Get `Hlas.exe` from the latest GitHub Actions run (artifact `Hlas-windows`) or from a release.
2. Start it. On first start it downloads the speech models (1.3 GB, once). The little pill at the bottom shows the progress.
3. Click into any text field, then:

| Keys | Action |
|---|---|
| hold **Ctrl+Win** | record; release to type the text |
| **Ctrl+Win+Space** | hands-free; tap Ctrl+Win to stop |
| while recording: **Ctrl+Win + 1 / 2 / 3 / 0** | force Slovak / German / English / auto from this point on |
| **Esc** | cancel |

**Optional free cleanup:** create a free key at console.groq.com and paste it under *Tray icon > Settings > Groq API key*. Or install [Ollama](https://ollama.com), run `ollama pull gemma3:12b`, and choose "Ollama" for fully offline cleanup (needs a strong PC).

Every dictation is also saved to `%APPDATA%\Hlas\history.jsonl`.

## Android

1. Install `Hlas-android.apk` (artifact `Hlas-android`). It needs a 64-bit phone with about 6 GB of RAM or more.
2. Open **Hlas** and tap: 1. Allow microphone, 2. Enable Hlas keyboard, 3. Switch to Hlas keyboard, 4. **Download offline models** (1.3 GB, use Wi-Fi).
3. In any app, switch to the Hlas keyboard. Tap the mic to talk and tap again to finish, or hold it and release. Tap the language chip while you talk to force a language. **ABC** switches back to your normal keyboard.

The optional cleanup with a free Groq key works the same as on Windows.

## Using it in other projects

```python
from hlas import Transcriber                       # pip install ./desktop
print(Transcriber().transcribe_file("memo.wav").text)
```

```bash
hlas models                      # download the offline models once
hlas transcribe memo.wav         # print the text
hlas listen                      # record from the mic until Enter, print the text
hlas serve                       # HTTP API on http://127.0.0.1:8765
curl -X POST http://127.0.0.1:8765/transcribe -H "Content-Type: audio/wav" --data-binary @memo.wav
```

The desktop hotkey also works inside VS Code, JetBrains IDEs, terminals and Claude Code. There, cleanup switches to a coding style that spells technical terms correctly.

## Licenses

- **App code:** this repository.
- **Speech models:** [NVIDIA Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) and [KInIT parakeet-tdt-0.6b-v3-sk](https://huggingface.co/kinit/parakeet-tdt-0.6b-v3-sk), both CC-BY-4.0. The apps download them from this repository's `models-v1` release, which `.github/workflows/models.yml` builds (see `models/README.md`).
- **Speech engine:** [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), Apache-2.0.

## Development

```bash
cd desktop && pip install -e ".[app,dev]" && pytest            # 38 tests
cd android && ./gradlew testDebugUnitTest assembleRelease        # needs the Android SDK
```

The cleanup prompt and the language picker exist in both `desktop/hlas/` and `android/.../`. Keep them in sync.
