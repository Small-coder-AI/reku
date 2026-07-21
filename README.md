# Reku

**[English](README.md) | [Русский](README.ru.md)**

Local push-to-talk dictation for Windows: hold a key — speak — the text appears at your cursor.
Fully offline: audio never leaves your machine. Russian and English out of the box (plus the 90+ languages Whisper knows).
Three engines under one hood: NVIDIA CUDA (faster-whisper), Intel iGPU/NPU (OpenVINO)
and AMD GPU (whisper.cpp + Vulkan) — the app picks whatever suits your hardware best
and falls back to a lighter model on weak machines.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/img/recording-dark.png">
    <img src="docs/img/recording-light.png" alt="Reku window while recording" width="400">
  </picture>
</p>

> **Note:** the app UI is currently in Russian; interface localization is on the roadmap.

## Why Reku

- **Big-model quality on an ordinary laptop.** Most local dictation tools run Whisper on
  the CPU, so on a regular ultrabook they are practically limited to the small/medium
  models — large-v3 is either too slow or won't run at all. Reku executes the full
  large-v3 (int8) on the Intel iGPU/NPU through OpenVINO: a plain laptop without a
  gaming GPU dictates with flagship-model accuracy. With an NVIDIA card it runs CUDA
  at full speed, and on AMD Radeon it uses whisper.cpp over Vulkan.
- **Actually offline.** No cloud, no account, no subscription — audio never leaves
  the machine.
- **Seriously tuned for Russian.** Cures the classic Whisper sores: Latin letters
  inside Russian words and phantom "subtitle credits" in pauses. English and 90+
  other languages work as well.
- **One command to install, the same command to update.** The script detects your
  hardware, installs Python by itself if missing and picks the right dependency
  profile (CUDA / Intel / AMD / CPU).

## Install

Open PowerShell and run:

```powershell
irm https://raw.githubusercontent.com/Small-coder-AI/reku/main/install.ps1 | % TrimStart ([char]0xFEFF) | iex
```

`% TrimStart ([char]0xFEFF)` strips the UTF-8 BOM that Windows PowerShell 5.1 keeps at the
front of the downloaded script — without it `iex` misreads the first comment line as a
command. The script detects your hardware, installs only what is needed (~1–3 GB) and creates shortcuts.
The speech model is downloaded on first launch. To update, run the same command again.
To uninstall, download install.ps1 and run it with `-Uninstall`.

If `irm` fails with "The underlying connection was closed", your Windows PowerShell
session has TLS 1.2 disabled — enable it and repeat the install command:

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
```

### Alternative: installer from Releases

Download `Reku-setup.exe` from the [releases page](https://github.com/Small-coder-AI/reku/releases)
and run it — a per-user install, no admin rights. Windows SmartScreen may warn
"Windows protected your PC" — click **"More info" → "Run anyway"** (the app is not signed
with a paid certificate, but the source is open). The installer bundles the CUDA and
OpenVINO engines (the AMD/Vulkan engine is a small on-demand download), so it is much
heavier than the script install above — the script remains the recommended path.

### Alternative: via uv (for developers)

With [uv](https://docs.astral.sh/uv/) installed, pick the extra matching your hardware:

```powershell
uv tool install "reku[cuda] @ git+https://github.com/Small-coder-AI/reku"    # NVIDIA GPU
uv tool install "reku[intel] @ git+https://github.com/Small-coder-AI/reku"   # Intel iGPU/NPU
uv tool install "reku @ git+https://github.com/Small-coder-AI/reku"          # CPU or AMD GPU
```

The AMD path needs no extra Python packages: the whisper.cpp (Vulkan) engine is
downloaded automatically on first launch (~45 MB, sha256-verified).

Then run `reku` in a **new** terminal window. Settings and models live in `%APPDATA%\Reku`.
Update later with `uv tool upgrade reku`.

## Usage

```powershell
.venv\Scripts\pythonw.exe -m reku      # GUI (window + tray, no console)
.venv\Scripts\python.exe -m reku       # GUI (with a console for logs/latency)
```

The window: dark borderless, mic orb (status by color), live waveform while recording,
a card with the recognized text, a record button, a language picker, gear → settings
(model/device/precision/hotkey/mode/VAD/filter). Closing the window minimizes to tray;
quit from the tray menu.

Wait for **Ready…** (the model takes ~6 s to load), then hold the hotkey (right Ctrl by
default), speak, release. The text is pasted at the cursor. **Keep a single instance
running** — each one loads its own copy of the model into VRAM.

The tray menu switches mode and language on the fly (writes to `config.json`).

## Settings — config.json

Created on first launch. The essentials:

| option | default | meaning |
|---|---|---|
| `model` / `compute_type` | `large-v3` / `auto` | which model to load; `large-v3-turbo` is nearly as accurate and several times faster |
| `device` | `auto` | `auto` → CUDA → AMD (Vulkan) → Intel GPU (OpenVINO) → CPU; explicit: `cuda`/`igpu`/`npu`/`amd`/`cpu` |
| `hotkey` | `ctrl_r` | pynput key name (`ctrl_r`, `f9`, …) or a single character |
| `mode` | `ptt` | `ptt` — hold to talk; `toggle` — press to start/stop |
| `theme` | `system` | `system` (follows Windows) / `dark` / `light` |
| `language` | `"ru"` | `"ru"` pins the language (fewer Latin-inside-Cyrillic artifacts); `""` — auto-detect |
| `initial_prompt` | Russian anchor | biases the decoder towards Cyrillic; keep it Russian, put terms into `hotwords` |
| `hotwords` | empty | your brands/terms, comma-separated (e.g. `GitHub, Docker, 1С`) — targeted bias |
| `beam_size` | `5` | `1` is faster, `5` is more accurate |
| `vad_filter` | `true` | cuts silence/noise — the **main** hallucination guard |
| `condition_on_previous_text` | `false` | `false` = fewer repetition loops |
| `no_repeat_ngram_size` | `0` | `0` = off: the n-gram ban cannot tell a loop from a legitimately repeated word and mangles the 2nd/3rd occurrence; loops are already covered by the layers above |
| `drop_hallucinations` | `true` | drops Whisper's trademark phantom captions (blocklist in postprocess.py) |
| `min_language_probability` | `0.0` | `>0` (e.g. 0.4) — mute output when language detection is uncertain (likely not speech) |
| `insert_method` | `paste` | `paste` (clipboard + Ctrl+V) or `type` (character by character) |

The defaults are tuned for **Russian** dictation. For another language, set `language`
accordingly (or `""` for auto-detect) and adapt `initial_prompt` to that language.

**Latin letters inside Russian words** are cured by the combo `language="ru"` + a Russian
`initial_prompt` + terms in `hotwords` (see `scripts/ab_test.py` — it compares configs on
the same voice take and prints the "% of mixed words"). The **theme** switches on the fly
in settings; `system` follows Windows. If the model failed to load (no network/device),
the window shows **"Error"** with the reason instead of hanging in "Loading".

## Development

```powershell
git clone https://github.com/Small-coder-AI/reku && cd reku
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m reku        # run
Get-ChildItem tests\test_*.py -Exclude test_frozen_smoke.py | ForEach-Object { .venv\Scripts\python $_.FullName }   # tests
```

Building the exe (fallback path):

```powershell
.\packaging\build.ps1              # plain build (dist\Reku\Reku.exe)
.\packaging\build.ps1 -Installer   # + installer (installer\Reku-setup.exe)
```

Result: `dist\Reku\Reku.exe` (double-click, tray icon). The model (~3 GB) is **not bundled** — it is downloaded on first launch into `%APPDATA%\Reku\models\`.
Build smoke test: `tests\test_frozen_smoke.py` (env var `REKU_SMOKE_DEVICE` = `cuda` on an NVIDIA machine or `igpu` on Intel).

**The installer** (Inno Setup, per-user — no admin rights) installs into `%LOCALAPPDATA%\Programs\Reku`, creates a Start Menu shortcut (+ an optional desktop one),
optional autostart and an uninstaller. Requires Inno Setup: `winget install JRSoftware.InnoSetup`.

**Releases**: pushing a `vX.Y.Z` tag triggers CI (`.github/workflows/release.yml`) that
builds the same installer and attaches it to the GitHub Release. Before tagging, bump
`version` in `pyproject.toml` and `__version__` in `reku/__init__.py` — CI verifies both
match the tag.

## How it works

### Why cuda_setup.py (an important GPU note)

CTranslate2 on Windows loads `cublas64_12.dll` / `cudnn*.dll` via plain
`LoadLibrary`, which only searches next to `ctranslate2.dll`, in System32 and on
**PATH**. The `nvidia-*` pip packages put their DLLs into `site-packages/nvidia/<lib>/bin`,
which is not on PATH. `os.add_dll_directory()` is **invisible** to ct2 (that flag is
honored by ctypes, not ct2). So `cuda_setup.py` adds those directories to `PATH` before
faster_whisper is imported. Without it `encode()` crashes: `cublas64_12.dll cannot be loaded`
(it looks like "running on CPU" but is actually a crash in a background thread).
`nvidia-cuda-runtime-cu12` is not needed — ct2 links cudart statically.

### Intel iGPU/NPU (OpenVINO)

On machines without NVIDIA, `auto` picks Intel graphics via OpenVINO GenAI:
ready-made int8 models are downloaded from HF (`OpenVINO/whisper-*-int8-ov`, the map is
`OV_MODEL_MAP` in backends.py); the first load compiles the model for your specific GPU
(tens of seconds, one-off), after that — cache in `ov_cache/` and a ~2–3 s start.
VAD works (Silero from faster-whisper), the hallucination filters work;
`min_language_probability` has NO effect on this path (the engine does not report language
confidence), decoding is greedy (beam_size is ignored); `hotwords` (the custom vocabulary)
are not supported by this engine either. Speed verified on Arc 140T; on weak iGPUs
(UHD 6xx and the like) large-v3 may compile/run slowly — pick `large-v3-turbo` or
`small` in settings. If OpenVINO fails to start in auto mode at all (driver/memory),
the app falls back to CPU + small. On machines without NVIDIA you may skip the
`nvidia-*` packages (`grep -v '^nvidia-' requirements.txt`). Benchmark on your own
phrases: `python scripts/bench_backends.py record`, then `run` (report in
`bench_audio/bench_results.md`).

### AMD GPU (whisper.cpp + Vulkan)

On machines with an AMD Radeon, `auto` picks the whisper.cpp engine over Vulkan —
the only mature GPU path on AMD/Windows (CTranslate2 has no ROCm build for Windows).
The engine (`whisper-server.exe`) is **our own CI build** from the
`engine-whisper-cpp-*-vulkan` release of this repo (official whisper.cpp releases ship
no Windows Vulkan binaries): it is downloaded on first use (~45 MB, sha256 pinned in
`reku/whisper_cpp.py`) into `%APPDATA%\Reku\engines` and runs as a local subprocess on
127.0.0.1; models are single-file ggml q5 quants from HF (`WCPP_MODEL_MAP` in
backends.py, large-v3 ≈ 1.1 GB — fits 8 GB VRAM easily). The very first inference
compiles Vulkan shaders (tens of seconds, one-off per machine — the driver caches them);
the app warms this up during model load. VAD and the hallucination filters work;
`min_language_probability` works too (an extra language-detection pass is requested only
when the filter is enabled); `hotwords`, `no_repeat_ngram_size` and
`condition_on_previous_text` are not supported by this engine. Server log for
diagnostics: `%APPDATA%\Reku\whisper-server.log`; a local engine build can be pointed to
via the `REKU_WHISPER_CPP_DIR` env var. The same Vulkan path runs on NVIDIA/Intel GPUs
as well (handy for testing: `"device": "amd"` in config.json).

## Files

- `reku/gui.py` — **desktop UI on PySide6** (window + tray). The main entry point.
- `reku/gui_theme.py` — palette + QSS. `reku/gui_widgets.py` — MicOrb + WaveformStrip.
- `reku/dictate.py` — the `DictationApp` core (record → transcribe → insert).
- `reku/config.py` / `config.json` — settings.
- `reku/postprocess.py` — hallucination filter (pure functions).
- `reku/cuda_setup.py` — puts the nvidia DLLs on PATH (see "Why cuda_setup.py" above). **Imported first.**
- `requirements.txt` (top-level pins) / `requirements.lock.txt` (full freeze).
- `reku/backends.py` — backend selection and management (faster-whisper, OpenVINO, whisper.cpp).
- `reku/whisper_cpp.py` — the AMD path machinery: engine download, whisper-server subprocess.
- `reku/model_store.py` — model download and caching.
- `tests/` — unit tests.
- `scripts/` — utility scripts (make_ico.py, bench_backends.py).
- `packaging/` — exe build (build.ps1, reku.spec, reku.iss).

## What is verified and what is not

Verified headless (no user involvement):
- GPU inference is genuine (0.69 s for 4 s of audio), the venv is self-contained;
- the `transcribe` → filter pipeline (silence/noise → empty output), thresholds, dedup, blocklist;
- tray construction (icons, menu) without errors.

Needs manual verification (requires a real keypress/window/GUI session):
- pasting text at the cursor in a real application;
- `toggle` mode and hotkey changes;
- tray icon appearance, menu clicks, color change by status.

## License

MIT — see [LICENSE](LICENSE).
