# Фаза 2: OpenVINO-бэкенд для Intel iGPU — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Быстрое локальное распознавание уровня large-v3 на ноутбуке Honor (Intel Arc 140T iGPU, без NVIDIA): OpenVINO-бэкенд + бенч-прототип до интеграции.

**Architecture:** Заглушка `OpenVINOBackend` (Фаза 1) наполняется реализацией на OpenVINO GenAI `WhisperPipeline`; готовые int8-модели скачиваются с HF (организация OpenVINO); VAD переиспользуется из faster-whisper; контракт `(segments, info)` сохраняется — dictate/postprocess/gui не меняют логики. До интеграции — standalone-бенч со воротами решения.

**Tech Stack:** Python 3.x, faster-whisper 1.2.1 (CPU-путь + VAD), openvino-genai (iGPU/NPU-путь), huggingface_hub (скачивание), PySide6 (UI), sounddevice.

**Спека:** `docs/superpowers/specs/2026-07-04-phase2-openvino-igpu-design.md`

## Global Constraints

- Рабочая директория: `d:\Dev\Whisper_PTT\whisper_ptt`; venv: `.venv` в корне репо.
- Машина: Windows 11, Core Ultra 7 255H, Intel Arc 140T, NVIDIA нет. Команды в примерах — Git Bash (`.venv/Scripts/python.exe …`).
- Пакеты `nvidia-*` из requirements.txt на этой машине НЕ ставятся (балласт ~1.2 ГБ; `cuda_setup.py` проверен — без пакета `nvidia` возвращает `[]`, не падает).
- Все юнит-тесты должны проходить на ЛЮБОЙ машине без GPU и **без установленного openvino** (все импорты `openvino*` и `faster_whisper` — ленивые, внутри функций/методов).
- Стиль тестов проекта — самодельные check-скрипты (`def check(name, cond)`, выход `SystemExit(0|1)`), НЕ pytest. Новые тесты — в том же стиле.
- Комментарии/докстринги — на русском; сообщения коммитов — на английском.
- Критерий ворот (из спеки): large-v3 на iGPU ≤ 3–4 с на фразу 3–5 с → дефолт large-v3, иначе large-v3-turbo.
- Модели качаются в `<data_dir>/models/<repo_id с заменой '/' на '_'>` (существующая раскладка `model_store.model_path`). `models/` в .gitignore — уже есть.
- Подтверждённые репо готовых моделей (HF API, 2026-07-04): `OpenVINO/whisper-{tiny,base,small,medium,large-v2,large-v3,large-v3-turbo}-int8-ov`, `OpenVINO/distil-whisper-large-v3-int8-ov`.

---

### Task 1: venv на ноуте + смоук CPU-пути

Репо на ноуте свежесклонировано, venv нет. Ставим окружение без CUDA-пакетов, проверяем существующие тесты и живой запуск.

**Files:**
- Create: `.venv/` (не в git)
- Никаких правок кода.

**Interfaces:**
- Produces: рабочий venv `.venv/Scripts/python.exe` со всеми зависимостями, кроме `nvidia-*`; скачанная CT2-модель `small` в `<data_dir>/models/small`.

- [ ] **Step 1: Найти системный Python и создать venv**

```bash
py -0p 2>/dev/null || python --version   # какие Python есть
py -m venv .venv 2>/dev/null || python -m venv .venv
.venv/Scripts/python.exe --version       # ожидаем 3.10–3.13
```

- [ ] **Step 2: Установить зависимости БЕЗ nvidia-***

```bash
grep -v '^nvidia-' requirements.txt > "$TEMP/req_nocuda.txt"
.venv/Scripts/python.exe -m pip install --upgrade pip
.venv/Scripts/python.exe -m pip install -r "$TEMP/req_nocuda.txt"
rm "$TEMP/req_nocuda.txt"
```

Expected: установлены faster-whisper 1.2.1, ctranslate2 4.7.2, numpy, sounddevice, pynput, pyperclip, PySide6, pystray, Pillow. Ошибок компиляции быть не должно (все — wheels).

- [ ] **Step 3: Прогнать существующие тесты**

```bash
.venv/Scripts/python.exe test_backends.py
.venv/Scripts/python.exe test_paths.py
.venv/Scripts/python.exe test_postprocess.py
.venv/Scripts/python.exe test_transcribe_pipeline.py
```

Expected: все `ИТОГ: ВСЕ ПРОШЛИ`. Если `test_transcribe_pipeline.py` требует модель/железо и падает по этой причине — зафиксировать в отчёте задачи и продолжить (он писался под RTX-ПК; решение о нём — на воротах Task 4).

- [ ] **Step 4: Живой смоук CPU (участие пользователя)**

```bash
.venv/Scripts/python.exe gui.py
```

Expected: `auto` → CPU → модель понижена до `small`, окно поднялось, статус «CPU (GPU не найден)». Первый запуск скачает `small` (~460 МБ) с прогрессом. Пользователь диктует фразу — текст вставляется. Это подтверждает: аудио-стек, хоткей, вставка и CPU-инференс на ноуте живы.

- [ ] **Step 5: Commit не нужен** (кода нет). Отметить в отчёте версии Python/pip и время загрузки `small`.

---

### Task 2: bench_backends.py — запись эталонных фраз

Standalone-диагностика (остаётся в репо, как `diag.py`). Режим `record`: пользователь надиктовывает 3–5 фраз, WAV сохраняются для воспроизводимых замеров.

**Files:**
- Create: `bench_backends.py`

**Interfaces:**
- Consumes: `config.data_dir()`, `model_store.model_path()` (существующие).
- Produces: CLI `bench_backends.py record|run`; WAV-файлы 16 кГц mono int16 в `<data_dir>/bench_audio/phrase_NN.wav`. Task 3 дополняет этот же файл режимом `run`.

- [ ] **Step 1: Написать каркас + режим record**

```python
"""Бенч бэкендов whisper_ptt: скорость/качество на реальном железе.

Standalone-диагностика (в приложение не импортируется):
  python bench_backends.py record   — надиктовать эталонные фразы (WAV 16 кГц)
  python bench_backends.py run      — прогнать матрицу бэкендов, напечатать таблицу

WAV лежат в <data_dir>/bench_audio/. Результаты — bench_results.md там же.
"""
import os
import sys
import time
import wave

import numpy as np

import config

SR = 16000
AUDIO_DIR = os.path.join(config.data_dir(), "bench_audio")


def wav_path(i: int) -> str:
    return os.path.join(AUDIO_DIR, f"phrase_{i:02d}.wav")


def save_wav(path: str, audio: np.ndarray) -> None:
    """float32 [-1..1] -> WAV int16 mono 16 кГц."""
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def load_wav(path: str) -> np.ndarray:
    """WAV int16 mono -> float32 [-1..1]."""
    with wave.open(path, "rb") as w:
        assert w.getframerate() == SR, f"{path}: ожидался {SR} Гц"
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def record() -> None:
    """Интерактивная запись фраз: Enter — старт, Enter — стоп."""
    import sounddevice as sd
    os.makedirs(AUDIO_DIR, exist_ok=True)
    print("Запись эталонных фраз (16 кГц). Советую 3–5 фраз: короткую (~3 с),")
    print("среднюю (~7 с), длинную (~15 с). Ввод 'q' — выход.\n")
    i = 1
    while os.path.exists(wav_path(i)):
        i += 1  # не затирать уже записанные
    while True:
        if input(f"Фраза {i}: Enter — начать запись (или 'q' + Enter — выход): ").strip():
            break
        frames = []
        stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                                callback=lambda d, n, t, s: frames.append(d.copy()))
        stream.start()
        input("● Говори... Enter — стоп: ")
        stream.stop(); stream.close()
        if not frames:
            print("Пусто, повтор.\n")
            continue
        audio = np.concatenate(frames).flatten()
        save_wav(wav_path(i), audio)
        print(f"  Сохранено: {wav_path(i)} ({len(audio) / SR:.1f} с)\n")
        i += 1


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "record":
        record()
    elif cmd == "run":
        run()  # Task 3
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
```

(Функция `run()` появляется в Task 3 — до тех пор `python bench_backends.py run` падает с NameError, это ожидаемо и не коммитится как готовое: коммит Task 2 содержит только record-режим; заглушку `run` НЕ писать, вместо вызова в `main` до Task 3 поставить `print("run: см. Task 3")`.)

- [ ] **Step 2: Проверить запись (участие пользователя)**

```bash
.venv/Scripts/python.exe bench_backends.py record
```

Пользователь надиктовывает 3–5 фраз (короткая/средняя/длинная, обычная речь с терминами из своей практики).

Expected: файлы `phrase_01.wav`… в `<data_dir>/bench_audio/`, длительности напечатаны верно.

- [ ] **Step 3: Проверить, что WAV читаются**

```bash
.venv/Scripts/python.exe -c "
import bench_backends as b, glob, os
for p in sorted(glob.glob(os.path.join(b.AUDIO_DIR, '*.wav'))):
    a = b.load_wav(p); print(p, f'{len(a)/b.SR:.1f}s', a.dtype)
"
```

Expected: список файлов, длительности, dtype float32.

- [ ] **Step 4: Commit**

```bash
git add bench_backends.py
git commit -m "feat(bench): add bench_backends.py record mode (reference phrases)"
```

---

### Task 3: bench_backends.py — прогон матрицы CPU vs iGPU

Режим `run`: одни и те же WAV через {CPU-CT2: small, large-v3-turbo, large-v3} × {OV-GPU: large-v3-turbo, large-v3}. Вызовы OpenVINO здесь — эталон для Task 6 (та же последовательность, живьём проверенная).

**Files:**
- Modify: `bench_backends.py` (добавить run-режим)

**Interfaces:**
- Consumes: `load_wav`, `AUDIO_DIR`, `SR` из Task 2; `model_store.model_path()`.
- Produces: `bench_results.md` в `<data_dir>/bench_audio/`; установленный пакет `openvino-genai`; скачанные OV-модели large-v3 и large-v3-turbo в раскладке model_store.

- [ ] **Step 1: Установить openvino-genai и проверить видимость GPU**

```bash
.venv/Scripts/python.exe -m pip install openvino-genai
.venv/Scripts/python.exe -c "
import openvino
core = openvino.Core()
print('devices:', core.available_devices)
for d in core.available_devices:
    print(d, '=', core.get_property(d, 'FULL_DEVICE_NAME'))
"
```

Expected: в списке есть `GPU` с именем вида `Intel(R) Arc(TM) 140T GPU`. NPU тоже может появиться.
**Если GPU нет** — драйвер Arc старый: сообщить пользователю, обновить Intel-драйвер через официальный установщик, перезагрузиться, повторить. Дальше не идти, пока GPU не виден.

- [ ] **Step 2: Дописать run-режим в bench_backends.py**

Заменить `print("run: см. Task 3")` на вызов `run()` и добавить код:

```python
# ── конфигурации бенча ──────────────────────────────────────────
INITIAL_PROMPT = ("Claude Code, Passivbot, Hyperliquid, 1С, "
                  "faster-whisper, Keenetic, OData.")
LANG = "ru"

CT2_MODELS = ["small", "large-v3-turbo", "large-v3"]
OV_REPOS = {
    "large-v3-turbo": "OpenVINO/whisper-large-v3-turbo-int8-ov",
    "large-v3": "OpenVINO/whisper-large-v3-int8-ov",
}
N_RUNS = 2   # 1-й прогон = холодный (компиляция/кэши), 2-й = честная скорость


def _bench_ct2(model_name: str, wavs: list) -> list[dict]:
    """CPU-путь как в приложении: faster-whisper int8, VAD, beam 5."""
    from faster_whisper import WhisperModel
    rows = []
    t0 = time.perf_counter()
    m = WhisperModel(model_name, device="cpu", compute_type="int8",
                     download_root=None)
    load_s = time.perf_counter() - t0
    for path, audio in wavs:
        times, text = [], ""
        for _ in range(N_RUNS):
            t0 = time.perf_counter()
            segments, info = m.transcribe(
                audio, language=LANG, beam_size=5, vad_filter=True,
                initial_prompt=INITIAL_PROMPT,
                condition_on_previous_text=False, no_repeat_ngram_size=3)
            text = " ".join(s.text.strip() for s in segments)  # генератор: инференс тут
            times.append(time.perf_counter() - t0)
        rows.append(dict(engine=f"CPU-ct2/{model_name}", wav=os.path.basename(path),
                         dur=len(audio) / SR, load=load_s,
                         cold=times[0], warm=times[-1], text=text))
    del m
    return rows


def _ensure_ov_model(repo: str) -> str:
    """Качает OV-модель в раскладку model_store (та же папка, что у приложения).
    snapshot_download сам докачивает недостающие файлы (возобновляемо)."""
    import model_store
    from huggingface_hub import snapshot_download
    path = model_store.model_path(repo)
    print(f"  модель {repo} -> {path}")
    snapshot_download(repo, local_dir=path)
    return path


def _bench_ov(model_name: str, repo: str, wavs: list) -> list[dict]:
    """iGPU-путь: OpenVINO GenAI WhisperPipeline. Эти вызовы — эталон для
    OpenVINOBackend (Task 6): kwargs generate() проверяются здесь живьём."""
    import openvino_genai
    path = _ensure_ov_model(repo)
    cache = os.path.join(config.data_dir(), "ov_cache")
    os.makedirs(cache, exist_ok=True)
    t0 = time.perf_counter()
    pipe = openvino_genai.WhisperPipeline(path, "GPU", CACHE_DIR=cache)
    load_s = time.perf_counter() - t0
    rows = []
    for path_w, audio in wavs:
        times, text = [], ""
        for _ in range(N_RUNS):
            t0 = time.perf_counter()
            result = pipe.generate(
                audio.tolist(), language=f"<|{LANG}|>", task="transcribe",
                return_timestamps=True, initial_prompt=INITIAL_PROMPT)
            chunks = getattr(result, "chunks", None) or []
            text = " ".join(c.text.strip() for c in chunks)
            times.append(time.perf_counter() - t0)
        rows.append(dict(engine=f"iGPU-ov/{model_name}", wav=os.path.basename(path_w),
                         dur=len(audio) / SR, load=load_s,
                         cold=times[0], warm=times[-1], text=text))
    del pipe
    return rows


def run() -> None:
    import glob
    paths = sorted(glob.glob(os.path.join(AUDIO_DIR, "*.wav")))
    if not paths:
        print("Нет WAV. Сначала: python bench_backends.py record")
        return
    wavs = [(p, load_wav(p)) for p in paths]
    rows = []
    for name in CT2_MODELS:
        print(f"\n=== CPU-ct2 / {name} ===")
        rows += _bench_ct2(name, wavs)
    for name, repo in OV_REPOS.items():
        print(f"\n=== iGPU-ov / {name} ===")
        rows += _bench_ov(name, repo, wavs)

    lines = ["| движок/модель | wav | длит., с | загрузка, с | 1-й прогон, с | повтор, с | RTF | текст |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['engine']} | {r['wav']} | {r['dur']:.1f} | {r['load']:.1f} "
                     f"| {r['cold']:.2f} | {r['warm']:.2f} | {r['warm'] / r['dur']:.2f} "
                     f"| {r['text']} |")
    table = "\n".join(lines)
    print("\n" + table)
    out = os.path.join(AUDIO_DIR, "bench_results.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Бенч {time.strftime('%Y-%m-%d %H:%M')}\n\n{table}\n")
    print(f"\nСохранено: {out}")
```

Примечания для исполнителя:
- `download_root=None` в WhisperModel — модель по имени качается в HF-кэш; CT2-`small` уже скачана приложением в Task 1 в model_store-раскладку, но бенчу проще по имени (кэш HF); при медленном интернете можно заменить на `model_store.model_path(name)`, если модель там есть.
- Объёмы докачки: CT2 `large-v3-turbo` ~1.6 ГБ, CT2 `large-v3` ~3.1 ГБ (float16-репо, независимо от int8-режима), OV large-v3 ~1.5 ГБ, OV turbo ~0.8 ГБ. **При слабом интернете CT2 `large-v3` допустимо исключить из `CT2_MODELS`** (спросить пользователя): на CPU она заведомо мимо критерия скорости, её warm-время оценивается по turbo (декодер turbo в ~4–6 раз легче). Исключение зафиксировать в bench_results.md.
- Если `pipe.generate(...)` с kwargs кидает TypeError (несовпадение сигнатуры) — перейти на config-объект: `c = pipe.get_generation_config(); c.language = "<|ru|>"; c.task = "transcribe"; c.return_timestamps = True; result = pipe.generate(audio.tolist(), c, initial_prompt=INITIAL_PROMPT)`. Зафиксировать рабочий вариант в отчёте — Task 6 обязан использовать ровно его.

- [ ] **Step 3: Прогнать бенч**

```bash
.venv/Scripts/python.exe bench_backends.py run
```

Expected: таблица со строками для всех 5 конфигураций × все WAV; `bench_results.md` записан. Холодный OV-прогон заметно дольше тёплого (компиляция); при повторном ЗАПУСКЕ скрипта холодный станет быстрым (CACHE_DIR работает) — проверить повторным запуском.

- [ ] **Step 4: Commit**

```bash
git add bench_backends.py
git commit -m "feat(bench): add run mode — CPU-ct2 vs iGPU-openvino matrix with md report"
```

---

### Task 4: ВОРОТА — решение по замерам (интерактив с пользователем)

Не кодовая задача. Вход: `bench_results.md`. Выход: два зафиксированных решения. **Выполняется главной сессией вместе с пользователем, не субагентом.**

- [ ] **Step 1: Свести таблицу и обсудить с пользователем**

Показать пользователю: warm-времена и RTF по каждой конфигурации, тексты для сравнения качества глазами (особенно термины из initial_prompt).

- [ ] **Step 2: Зафиксировать решение №1 — путь**

Критерий: iGPU-ov быстрее CPU-ct2 на той же модели И качество текста не хуже → путь OpenVINO подтверждён.
Если iGPU медленнее CPU или качество провалено → СТОП: остаёмся на CPU+turbo (только Task 8-9 в урезанном виде: turbo в MODELS, README), дизайн-ревизия со спекой.

- [ ] **Step 3: Зафиксировать решение №2 — карта подстановки авто-режима**

- large-v3 warm ≤ 3–4 с на короткой фразе (3–5 с) → `IGPU_AUTO_SUBSTITUTE = {}` (в авто-режиме на iGPU модель конфига не понижается; дефолт конфига и так large-v3);
- иначе → `IGPU_AUTO_SUBSTITUTE = {"large-v3": "large-v3-turbo", "large-v2": "large-v3-turbo", "large": "large-v3-turbo", "large-v1": "large-v3-turbo", "distil-large-v2": "large-v3-turbo", "distil-large-v3": "large-v3-turbo", "distil-large-v3.5": "large-v3-turbo"}` (тяжёлые не-turbo → turbo).

Дописать решения в конец `bench_results.md` (строки `ПУТЬ: openvino|cpu` и `IGPU_AUTO_SUBSTITUTE: {...}`) — Task 7 читает значение отсюда.

- [ ] **Step 4: Сообщить о судьбе `test_transcribe_pipeline.py`**, если он падал в Task 1 (починка вне скоупа — зафиксировать known issue в отчёте ворот).

---

### Task 5: model_store — скачивание OV-моделей + вид модели у бэкенда

TDD. `is_cached` учится видеть OV-маркер; `ensure_downloaded` получает параметр `kind`; у `Backend` появляется `model_kind`; `dictate.load_model` передаёт kind.

**Files:**
- Modify: `model_store.py`
- Modify: `backends.py` (свойство `model_kind` у Backend/CTranslate2Backend)
- Modify: `dictate.py:91` (вызов ensure_downloaded)
- Test: `test_paths.py` (model_store), `test_backends.py` (model_kind)

**Interfaces:**
- Produces (Task 6/7 и dictate.py зависят от них):
  - `model_store.is_cached(model: str) -> bool` — True если есть `model.bin` (CT2) ИЛИ `.download_complete` (OV);
  - `model_store.ensure_downloaded(model: str, kind: str = "ct2", on_progress=None) -> str`;
  - `Backend.model_kind` property → `"ct2"` (база, CTranslate2Backend) / `"ov"` (OpenVINOBackend, Task 6); у ApiBackend не используется (model_id=None).

- [ ] **Step 1: Написать падающие тесты в test_paths.py**

Добавить в конец test_paths.py (перед `print("\nИТОГ:...`)):

```python
# ── model_store: OV-модели (маркер + скачивание через snapshot_download) ──
_ov_id = "OpenVINO/whisper-large-v3-int8-ov"
_ov_dir = model_store.model_path(_ov_id)

# is_cached видит OV-маркер .download_complete
os.makedirs(_ov_dir, exist_ok=True)
open(os.path.join(_ov_dir, ".download_complete"), "w").close()
ok &= check("is_cached=True по OV-маркеру", model_store.is_cached(_ov_id) is True)

# is_cached видит model.bin (CT2, существующее поведение)
_ct2_dir = model_store.model_path("small")
os.makedirs(_ct2_dir, exist_ok=True)
open(os.path.join(_ct2_dir, "model.bin"), "w").close()
ok &= check("is_cached=True по model.bin", model_store.is_cached("small") is True)

# ensure_downloaded(kind="ov"): зовёт huggingface_hub.snapshot_download и пишет маркер
import huggingface_hub
_calls = []
_orig_sd = huggingface_hub.snapshot_download
huggingface_hub.snapshot_download = lambda repo, local_dir: (_calls.append((repo, local_dir)),
                                                             os.makedirs(local_dir, exist_ok=True))[-1]
try:
    _new_id = "OpenVINO/whisper-large-v3-turbo-int8-ov"
    p = model_store.ensure_downloaded(_new_id, kind="ov")
    ok &= check("ensure_downloaded(ov) зовёт snapshot_download",
                _calls and _calls[0][0] == _new_id)
    ok &= check("ensure_downloaded(ov) пишет маркер",
                os.path.isfile(os.path.join(p, ".download_complete")))
    ok &= check("повторный вызов не качает снова (кэш)",
                model_store.ensure_downloaded(_new_id, kind="ov") == p and len(_calls) == 1)
finally:
    huggingface_hub.snapshot_download = _orig_sd
```

- [ ] **Step 2: Прогнать — убедиться, что падают**

```bash
.venv/Scripts/python.exe test_paths.py
```

Expected: FAIL на «is_cached=True по OV-маркеру» и TypeError на `kind="ov"` (нет такого параметра).

- [ ] **Step 3: Реализовать в model_store.py**

Заменить функции `is_cached` и `ensure_downloaded` целиком:

```python
_OV_MARKER = ".download_complete"


def is_cached(model: str) -> bool:
    """Скачана ли модель: model.bin (CT2) либо маркер завершённости (OV).
    Для OV маркер надёжнее перечня файлов — состав репо может меняться."""
    p = model_path(model)
    return (os.path.isfile(os.path.join(p, "model.bin"))
            or os.path.isfile(os.path.join(p, _OV_MARKER)))


def ensure_downloaded(model: str, kind: str = "ct2", on_progress=None) -> str:
    """Гарантирует наличие модели локально. kind: 'ct2' (faster-whisper)
    или 'ov' (репо OpenVINO с HF через snapshot_download; возобновляемо).
    on_progress(model) зовётся один раз перед началом скачивания (для UI)."""
    p = model_path(model)
    if is_cached(model):
        return p
    if on_progress:
        on_progress(model)
    if kind == "ov":
        from huggingface_hub import snapshot_download
        snapshot_download(model, local_dir=p)
        open(os.path.join(p, _OV_MARKER), "w").close()
    else:
        from faster_whisper.utils import download_model
        download_model(model, output_dir=p)
    return p
```

- [ ] **Step 4: Добавить Backend.model_kind в backends.py**

В класс `Backend` (после свойства `model_id`):

```python
    @property
    def model_kind(self) -> str:
        """Вид модели для model_store.ensure_downloaded: 'ct2' | 'ov'."""
        return "ct2"
```

(CTranslate2Backend наследует "ct2"; OpenVINOBackend переопределит в Task 6.)

В `dictate.py` строка 91 — передать kind:

```python
            model_store.ensure_downloaded(
                mid, kind=self.backend.model_kind,
                on_progress=lambda m: print(
                    f"Скачиваю модель '{m}' (первый запуск, может занять минуты)…",
                    flush=True))
```

В test_backends.py добавить перед `print("\nИТОГ:...`)):

```python
# model_kind: CT2 -> "ct2"
ok &= check("CTranslate2Backend.model_kind == ct2",
            CTranslate2Backend("small", "cpu", "int8").model_kind == "ct2")
```

- [ ] **Step 5: Прогнать тесты**

```bash
.venv/Scripts/python.exe test_paths.py && .venv/Scripts/python.exe test_backends.py
```

Expected: оба `ИТОГ: ВСЕ ПРОШЛИ`.

- [ ] **Step 6: Commit**

```bash
git add model_store.py backends.py dictate.py test_paths.py test_backends.py
git commit -m "feat(models): OV model downloads via snapshot_download + completion marker"
```

---

### Task 6: backends — адаптер результата, VAD-шаг, OpenVINOBackend

TDD. Чистые функции-адаптеры + наполнение заглушки OpenVINOBackend. Все импорты openvino/faster_whisper — ленивые. Вызов `pipe.generate(...)` — РОВНО тот, что подтверждён бенчем (Task 3, включая примечание про фолбэк на config-объект, если он понадобился).

**Files:**
- Modify: `backends.py` (OV_MODEL_MAP, ov_lang_token, chunks_to_segments, make_ov_info, apply_vad, OpenVINOBackend)
- Test: `test_backends.py`

**Interfaces:**
- Consumes: `model_store.model_path`, `model_store._data_dir` (Task 5); контракт `Backend` (Фаза 1).
- Produces (Task 7 зависит):
  - `OV_MODEL_MAP: dict[str, str]` — имя модели конфига → HF-репо;
  - `OpenVINOBackend(model: str, device: str)` — device `"igpu"|"npu"`; `.load()`, `.transcribe(audio, cfg) -> (list, SimpleNamespace)`, `.device_label`, `.model_id`, `.model_kind == "ov"`;
  - `ov_lang_token(language: str) -> str | None`; `chunks_to_segments(chunks) -> list`; `make_ov_info(language: str, duration: float)`; `apply_vad(audio, sample_rate=16000) -> np.ndarray | None`.

- [ ] **Step 1: Написать падающие тесты в test_backends.py**

Добавить перед итоговым print:

```python
# ── OV-адаптеры (чистые функции, без openvino) ────────────────
from backends import ov_lang_token, chunks_to_segments, make_ov_info, OV_MODEL_MAP

ok &= check("ov_lang_token ru", ov_lang_token("ru") == "<|ru|>")
ok &= check("ov_lang_token пусто -> None", ov_lang_token("") is None)

_chunks = [S(text=" Привет ", start_ts=0.0, end_ts=1.2),
           S(text="мир", start_ts=1.2, end_ts=2.0)]
_segs = chunks_to_segments(_chunks)
ok &= check("chunks_to_segments: 2 сегмента", len(_segs) == 2)
ok &= check("chunks_to_segments: контракт .text/.start/.end/.compression_ratio",
            _segs[0].text == " Привет " and _segs[0].start == 0.0
            and _segs[1].end == 2.0 and _segs[0].compression_ratio == 0.0)
ok &= check("chunks_to_segments: пусто", chunks_to_segments([]) == [])

_info = make_ov_info("ru", 3.5)
ok &= check("make_ov_info: контракт info",
            _info.language == "ru" and _info.language_probability == 1.0
            and _info.duration == 3.5)

ok &= check("OV_MODEL_MAP: large-v3 и turbo",
            OV_MODEL_MAP["large-v3"] == "OpenVINO/whisper-large-v3-int8-ov"
            and OV_MODEL_MAP["large-v3-turbo"] == "OpenVINO/whisper-large-v3-turbo-int8-ov"
            and OV_MODEL_MAP["turbo"] == OV_MODEL_MAP["large-v3-turbo"])

# ── OpenVINOBackend: свойства и понятная ошибка про неизвестную модель ──
_ovb = OpenVINOBackend(model="large-v3", device="igpu")
ok &= check("OV device_label GPU", _ovb.device_label == "Intel GPU (OpenVINO)")
ok &= check("OV model_kind", _ovb.model_kind == "ov")
ok &= check("OV model_id -> репо", _ovb.model_id == "OpenVINO/whisper-large-v3-int8-ov")
ok &= check("OV npu label",
            OpenVINOBackend(model="large-v3", device="npu").device_label
            == "Intel NPU (OpenVINO)")
try:
    OpenVINOBackend(model="no-such-model", device="igpu").load()
    ok &= check("OV.load: ValueError для неизвестной модели", False)
except ValueError as e:
    ok &= check("OV.load: ValueError для неизвестной модели", "no-such-model" in str(e))

# ── OpenVINOBackend.transcribe: фейковый пайплайн, без железа ──
class _FakePipe:
    def generate(self, samples, **kw):
        assert isinstance(samples, list), "generate ждёт list[float]"
        return S(chunks=[S(text="тест", start_ts=0.0, end_ts=1.0)])

_ovb2 = OpenVINOBackend(model="large-v3", device="igpu")
_ovb2._pipe = _FakePipe()
_cfg = S(language="ru", vad_filter=False, initial_prompt="", beam_size=5,
         condition_on_previous_text=False, no_repeat_ngram_size=3)
import numpy as np
_segs2, _info2 = _ovb2.transcribe(np.zeros(16000, dtype=np.float32), _cfg)
ok &= check("OV.transcribe: сегменты через адаптер",
            len(_segs2) == 1 and _segs2[0].text == "тест")
ok &= check("OV.transcribe: info.language_probability=1.0",
            _info2.language_probability == 1.0 and _info2.duration == 1.0)

# ── apply_vad: тишина -> None (реальный Silero из faster-whisper) ──
from backends import apply_vad
ok &= check("apply_vad: тишина -> None",
            apply_vad(np.zeros(16000, dtype=np.float32)) is None)

# apply_vad: «речь» моком faster_whisper.vad
import faster_whisper.vad as _fwvad
_orig_get, _orig_collect = _fwvad.get_speech_timestamps, _fwvad.collect_chunks
_fwvad.get_speech_timestamps = lambda audio, **kw: [{"start": 0, "end": 8000}]
_fwvad.collect_chunks = lambda audio, chunks, **kw: ([audio[:8000]], [{}])
try:
    _out = apply_vad(np.ones(16000, dtype=np.float32))
    ok &= check("apply_vad: речь -> склеенные куски", _out is not None and len(_out) == 8000)
finally:
    _fwvad.get_speech_timestamps, _fwvad.collect_chunks = _orig_get, _orig_collect

# VAD-гейт в transcribe: нет речи -> пустой результат без вызова generate
class _BoomPipe:
    def generate(self, *a, **kw):
        raise AssertionError("generate не должен зваться при пустом VAD")

_ovb3 = OpenVINOBackend(model="large-v3", device="igpu")
_ovb3._pipe = _BoomPipe()
_cfg_vad = S(language="ru", vad_filter=True, initial_prompt="", beam_size=5,
             condition_on_previous_text=False, no_repeat_ngram_size=3)
_segs3, _info3 = _ovb3.transcribe(np.zeros(16000, dtype=np.float32), _cfg_vad)
ok &= check("OV.transcribe: VAD-гейт (тишина -> пусто, generate не зван)",
            _segs3 == [] and _info3.duration == 1.0)
```

- [ ] **Step 2: Прогнать — убедиться, что падают**

```bash
.venv/Scripts/python.exe test_backends.py
```

Expected: ImportError (нет ov_lang_token и т.д.).

- [ ] **Step 3: Реализовать в backends.py**

После `CPU_FALLBACK_MODEL = "small"` добавить:

```python
# Готовые int8-модели OpenVINO на HF (проверено по HF API 2026-07-04).
# Имя модели из конфига -> репо для скачивания.
OV_MODEL_MAP = {
    "large-v3": "OpenVINO/whisper-large-v3-int8-ov",
    "large-v3-turbo": "OpenVINO/whisper-large-v3-turbo-int8-ov",
    "turbo": "OpenVINO/whisper-large-v3-turbo-int8-ov",
    "distil-large-v3": "OpenVINO/distil-whisper-large-v3-int8-ov",
    "large-v2": "OpenVINO/whisper-large-v2-int8-ov",
    "medium": "OpenVINO/whisper-medium-int8-ov",
    "small": "OpenVINO/whisper-small-int8-ov",
    "base": "OpenVINO/whisper-base-int8-ov",
    "tiny": "OpenVINO/whisper-tiny-int8-ov",
}


def ov_lang_token(language):
    """'ru' -> '<|ru|>' (формат WhisperPipeline); пустой язык -> None (авто)."""
    return f"<|{language}|>" if language else None


def chunks_to_segments(chunks):
    """result.chunks (WhisperPipeline) -> сегменты контракта faster-whisper.
    Наш postprocess читает .text и .compression_ratio (у OV её нет -> 0.0)."""
    from types import SimpleNamespace
    return [SimpleNamespace(text=c.text, start=c.start_ts, end=c.end_ts,
                            compression_ratio=0.0) for c in (chunks or [])]


def make_ov_info(language, duration):
    """info контракта faster-whisper. ВАЖНО: WhisperPipeline не сообщает
    уверенность в языке -> language_probability всегда 1.0, поэтому фильтр
    min_language_probability в OV-пути не действует (осознанная деградация)."""
    from types import SimpleNamespace
    return SimpleNamespace(language=language or "", language_probability=1.0,
                           duration=duration)


def apply_vad(audio, sample_rate=16000):
    """VAD-шаг для OV-пути: Silero из faster-whisper (он всё равно установлен
    для CPU/CUDA). None = речи нет; иначе склейка речевых кусков."""
    import numpy as np
    from faster_whisper.vad import get_speech_timestamps, collect_chunks
    chunks = get_speech_timestamps(audio, sampling_rate=sample_rate)
    if not chunks:
        return None
    pieces, _ = collect_chunks(audio, chunks, sampling_rate=sample_rate)
    return np.concatenate(pieces)
```

Класс `OpenVINOBackend` заменить целиком:

```python
class OpenVINOBackend(Backend):
    """Intel iGPU/NPU через OpenVINO GenAI WhisperPipeline.

    Модели — готовые int8 с HF (OV_MODEL_MAP), без конвертации на машине.
    Вызов generate() повторяет проверенный бенчем (bench_backends.py).
    """
    name = "openvino"

    def __init__(self, model, device):
        self.model_name = model
        self.device = device          # "igpu" | "npu"
        self._pipe = None

    @property
    def device_label(self) -> str:
        return ("Intel NPU (OpenVINO)" if self.device == "npu"
                else "Intel GPU (OpenVINO)")

    @property
    def model_id(self):
        return OV_MODEL_MAP.get(self.model_name)

    @property
    def model_kind(self) -> str:
        return "ov"

    def load(self):
        import os
        rid = self.model_id
        if rid is None:
            raise ValueError(
                f"модель {self.model_name!r} недоступна для Intel GPU/NPU; "
                f"выбери одну из: {', '.join(sorted(OV_MODEL_MAP))}")
        import openvino_genai       # лениво: на машинах без OV не импортируется
        import model_store
        cache = os.path.join(model_store._data_dir(), "ov_cache")
        os.makedirs(cache, exist_ok=True)
        dev = "NPU" if self.device == "npu" else "GPU"
        props = {"CACHE_DIR": cache}
        if self.device == "npu":
            props["STATIC_PIPELINE"] = True   # требование WhisperPipeline на NPU
        self._pipe = openvino_genai.WhisperPipeline(
            model_store.model_path(rid), dev, **props)

    def transcribe(self, audio, cfg):
        duration = len(audio) / 16000.0
        if cfg.vad_filter:
            audio = apply_vad(audio)
            if audio is None:
                return [], make_ov_info(cfg.language, duration)
        kwargs = dict(task="transcribe", return_timestamps=True)
        lang = ov_lang_token(cfg.language)
        if lang:
            kwargs["language"] = lang
        if cfg.initial_prompt:
            kwargs["initial_prompt"] = cfg.initial_prompt
        result = self._pipe.generate(audio.tolist(), **kwargs)
        segments = chunks_to_segments(getattr(result, "chunks", None))
        return segments, make_ov_info(cfg.language, duration)
```

(`beam_size`, `no_repeat_ngram_size`, `condition_on_previous_text` — CT2-специфика, в GenAI-путь не пробрасываются: greedy-декод, качество подтверждено бенчем на воротах.)

- [ ] **Step 4: Прогнать тесты**

```bash
.venv/Scripts/python.exe test_backends.py
```

Expected: `ИТОГ: ВСЕ ПРОШЛИ`. Если тест «apply_vad: тишина» медленный/падает из-за отсутствия onnxruntime — проверить `pip show onnxruntime` (зависимость faster-whisper; должен стоять с Task 1).

- [ ] **Step 5: Commit**

```bash
git add backends.py test_backends.py
git commit -m "feat(backends): implement OpenVINOBackend (GenAI WhisperPipeline, VAD, result adapter)"
```

---

### Task 7: backends — авто-детект Intel GPU и маршрутизация igpu/npu

TDD. `resolve_runtime` получает `ov_gpu_available`, авто-цепочка cuda → igpu → cpu; подстановка модели на iGPU по результату ворот; `select_backend` маршрутизирует igpu/npu.

**Files:**
- Modify: `backends.py` (`IGPU_AUTO_SUBSTITUTE`, `_ov_gpu_available`, `resolve_runtime`, `select_backend`)
- Modify: `config.py:30` (комментарий поля device)
- Test: `test_backends.py`

**Interfaces:**
- Consumes: `OpenVINOBackend(model, device)` из Task 6; решение ворот из `bench_results.md` (Task 4).
- Produces:
  - `resolve_runtime(device, compute_type, model, *, cuda_available, ov_gpu_available=False)` — прежний 3-кортеж; существующие вызовы без нового kwarg работают как раньше;
  - `select_backend(cfg, *, cuda_probe=None, ov_probe=None)`;
  - `IGPU_AUTO_SUBSTITUTE: dict[str, str]`, `_ov_gpu_available() -> bool`.

- [ ] **Step 1: Написать падающие тесты в test_backends.py**

```python
# ── маршрутизация igpu/npu ────────────────────────────────────
from backends import IGPU_AUTO_SUBSTITUTE, HEAVY_MODELS

# auto: cuda главнее igpu
ok &= check("auto+cuda(+ov) -> cuda",
            resolve_runtime("auto", "auto", "large-v3",
                            cuda_available=True, ov_gpu_available=True)
            == ("cuda", "float16", "large-v3"))

# auto: нет cuda, есть Intel GPU -> igpu; подстановка модели по карте ворот
_expected_mdl = IGPU_AUTO_SUBSTITUTE.get("large-v3", "large-v3")
ok &= check("auto+no-cuda+ov -> igpu (+карта ворот)",
            resolve_runtime("auto", "auto", "large-v3",
                            cuda_available=False, ov_gpu_available=True)
            == ("igpu", "int8", _expected_mdl))

# auto: лёгкая модель на igpu не трогается
ok &= check("auto+ov+light -> igpu/base",
            resolve_runtime("auto", "auto", "base",
                            cuda_available=False, ov_gpu_available=True)
            == ("igpu", "int8", "base"))

# карта подстановки понижает только тяжёлые
ok &= check("IGPU_AUTO_SUBSTITUTE только про HEAVY_MODELS",
            set(IGPU_AUTO_SUBSTITUTE) <= HEAVY_MODELS)

# auto: ничего нет -> cpu + понижение (существующее поведение, без нового kwarg)
ok &= check("auto+ничего -> cpu/small (совместимость)",
            resolve_runtime("auto", "auto", "large-v3", cuda_available=False)
            == ("cpu", "int8", "small"))

# явный igpu: probe не нужен, модель не понижается
ok &= check("явный igpu без понижения",
            resolve_runtime("igpu", "auto", "large-v3", cuda_available=False)
            == ("igpu", "int8", "large-v3"))

# явный npu
ok &= check("явный npu",
            resolve_runtime("npu", "auto", "large-v3", cuda_available=False)
            == ("npu", "int8", "large-v3"))

# select_backend: no-cuda + ov -> OpenVINOBackend igpu
_b_ov = select_backend(S(device="auto", compute_type="auto", model="base"),
                       cuda_probe=lambda: False, ov_probe=lambda: True)
ok &= check("select: auto -> OpenVINOBackend/igpu",
            isinstance(_b_ov, OpenVINOBackend) and _b_ov.device == "igpu"
            and _b_ov.model_name == "base")

# select_backend: явный igpu не зовёт пробы
_probe_calls = []
_b_igpu = select_backend(S(device="igpu", compute_type="auto", model="large-v3"),
                         cuda_probe=lambda: _probe_calls.append("cuda") or False,
                         ov_probe=lambda: _probe_calls.append("ov") or False)
ok &= check("select: явный igpu без проб",
            isinstance(_b_igpu, OpenVINOBackend) and _probe_calls == [])

# select_backend: cuda есть -> ov-проба не зовётся (ленивость)
_ov_calls = []
_b_cuda = select_backend(S(device="auto", compute_type="auto", model="small"),
                         cuda_probe=lambda: True,
                         ov_probe=lambda: _ov_calls.append(1) or True)
ok &= check("select: cuda найден -> ov-проба не звана",
            isinstance(_b_cuda, CTranslate2Backend) and _ov_calls == [])
```

- [ ] **Step 2: Прогнать — убедиться, что падают**

```bash
.venv/Scripts/python.exe test_backends.py
```

Expected: ImportError на IGPU_AUTO_SUBSTITUTE / TypeError на ov_gpu_available.

- [ ] **Step 3: Реализовать в backends.py**

После `OV_MODEL_MAP` добавить (значение — РЕЗУЛЬТАТ ВОРОТ Task 4 из bench_results.md; ниже вариант «large-v3 уложилась» — пустая карта):

```python
# Подстановка модели в АВТО-режиме на iGPU — результат ворот бенча
# (docs/superpowers/specs/2026-07-04-phase2-openvino-igpu-design.md, «Порядок работ»).
# Пустая карта = large-v3 уложилась в критерий 3–4 с, ничего не понижаем.
IGPU_AUTO_SUBSTITUTE = {}


def _ov_gpu_available() -> bool:
    """Есть ли Intel GPU для OpenVINO. Любой сбой (нет пакета/драйвера) = нет."""
    try:
        import openvino
        return "GPU" in openvino.Core().available_devices
    except Exception:
        return False
```

`resolve_runtime` заменить целиком:

```python
def resolve_runtime(device, compute_type, model, *, cuda_available,
                    ov_gpu_available=False):
    """Чистая функция: ('auto'|'cuda'|'cpu'|'igpu'|'npu', compute, model) ->
    конкретные значения. Авто-цепочка: cuda -> igpu -> cpu. Понижение модели —
    ТОЛЬКО в auto: на cpu тяжёлые -> small, на igpu — по карте ворот бенча."""
    auto = (device == "auto")
    if auto:
        dev = "cuda" if cuda_available else ("igpu" if ov_gpu_available else "cpu")
    else:
        dev = device

    comp = compute_type
    if comp in ("", "auto", None):
        comp = "float16" if dev == "cuda" else "int8"

    mdl = model
    if auto and dev == "cpu" and model in HEAVY_MODELS:
        mdl = CPU_FALLBACK_MODEL
    if auto and dev == "igpu":
        mdl = IGPU_AUTO_SUBSTITUTE.get(model, model)

    return dev, comp, mdl
```

`select_backend` заменить целиком:

```python
def select_backend(cfg, *, cuda_probe=None, ov_probe=None):
    """Маршрутизация: cfg.device -> конкретный Backend (ещё не загружен).
    Пробы зовутся только в auto-режиме, ov-проба — только если CUDA нет."""
    if cfg.device == "api":
        return ApiBackend(cfg)
    cuda = (cuda_probe or _cuda_available)() if cfg.device == "auto" else False
    ov = ((ov_probe or _ov_gpu_available)()
          if (cfg.device == "auto" and not cuda) else False)
    dev, comp, mdl = resolve_runtime(cfg.device, cfg.compute_type, cfg.model,
                                     cuda_available=cuda, ov_gpu_available=ov)
    if dev in ("igpu", "npu"):
        return OpenVINOBackend(model=mdl, device=dev)
    return CTranslate2Backend(model=mdl, device=dev, compute_type=comp)
```

ВНИМАНИЕ: в старом коде `select_backend` звал `probe()` всегда (и для явного cpu/cuda). Новый зовёт только в auto — существующий тест «явный cpu НЕ понижает модель» использует resolve_runtime напрямую и не ломается; поведение для явного `cuda` то же (resolve_runtime вернёт cuda как есть).

ОБЯЗАТЕЛЬНО обновить существующий тест в test_backends.py (строка ~52): на машине с установленным openvino и живым GPU дефолтная ov-проба вернёт True и тест начнёт получать OpenVINOBackend вместо CPU. Замокать и её:

```python
b2 = select_backend(cfg_loc, cuda_probe=lambda: False, ov_probe=lambda: False)
```

(ожидания теста — CTranslate2Backend/cpu/small — не меняются).

В `config.py` обновить комментарий поля:

```python
    device: str = "auto"             # auto / cuda / cpu / igpu / npu / api
```

- [ ] **Step 4: Прогнать все тесты**

```bash
.venv/Scripts/python.exe test_backends.py && .venv/Scripts/python.exe test_paths.py
```

Expected: `ИТОГ: ВСЕ ПРОШЛИ` оба.

- [ ] **Step 5: Commit**

```bash
git add backends.py config.py test_backends.py
git commit -m "feat(backends): auto-detect Intel GPU, route igpu/npu to OpenVINOBackend"
```

---

### Task 8: gui — пункты устройства и модель turbo

**Files:**
- Modify: `gui.py:27-30` (MODELS, DEVICES)

**Interfaces:**
- Consumes: значения device `igpu`/`npu` (Task 7), модель `large-v3-turbo` (OV_MODEL_MAP Task 6; для CPU-пути faster-whisper тоже знает это имя).

- [ ] **Step 1: Обновить карты комбобоксов**

```python
MODELS = ["large-v3", "large-v3-turbo", "large-v2", "medium", "small", "base", "tiny"]
COMPUTES = ["float16", "int8_float16", "int8", "float32"]
DEVICES = [("Авто", "auto"), ("GPU (CUDA)", "cuda"),
           ("Intel GPU (OpenVINO)", "igpu"), ("Intel NPU (эксперимент)", "npu"),
           ("CPU", "cpu"), ("API (облако)", "api")]
```

(Подсказка `CPU (GPU не найден)` в `_update_hint` уже корректна: она срабатывает только при `auto`→cpu, т.е. когда нет ни CUDA, ни Intel GPU. При `auto`→igpu покажется `device_label` бэкенда — «Intel GPU (OpenVINO)».)

- [ ] **Step 2: Прогнать смоук GUI**

```bash
.venv/Scripts/python.exe smoke_gui.py
```

Expected: без ошибок (как в Фазе 1).

- [ ] **Step 3: Живая проверка (участие пользователя)**

```bash
.venv/Scripts/python.exe gui.py
```

Expected: `auto` теперь резолвится в igpu; статус — «Intel GPU (OpenVINO)»; первый запуск качает OV-модель (уже скачана бенчем — мгновенно) и компилирует (кэш от бенча — быстро). Пользователь диктует — текст вставляется, время сопоставимо с warm-замером бенча.

- [ ] **Step 4: Commit**

```bash
git add gui.py
git commit -m "feat(gui): Intel GPU/NPU device options + large-v3-turbo model"
```

---

### Task 9: Документация, requirements, финальный прогон

**Files:**
- Modify: `README.md` (раздел «Настройка», описание device; заметка про OV-путь)
- Modify: `requirements.txt`, `requirements.lock.txt`

**Interfaces:**
- Consumes: всё построенное; фактические версии пакетов из venv ноутбука.

- [ ] **Step 1: requirements.txt — добавить openvino-genai**

После блока nvidia-* добавить:

```text
# Intel iGPU/NPU-путь (OpenVINOBackend): GenAI-пайплайн + рантайм.
# На чисто-NVIDIA машинах безвреден (авто-детект выберет CUDA раньше).
openvino-genai==<фактическая версия из pip show openvino-genai>
```

В `requirements.lock.txt` добавить строки `openvino`, `openvino-genai`, `openvino-tokenizers` с фактическими версиями (`pip freeze | grep -i openvino`). Строки nvidia-* в lock НЕ трогать (сняты с RTX-ПК, там они нужны).

- [ ] **Step 2: README — device и OV-заметка**

В таблице конфига строку про модель/устройство заменить на актуальную:

```markdown
| `model` / `compute_type` | `large-v3` / `auto` | какую модель грузить; `large-v3-turbo` — почти то же качество, в разы быстрее |
| `device` | `auto` | `auto` → CUDA → Intel GPU (OpenVINO) → CPU; явно: `cuda`/`igpu`/`npu`/`cpu` |
```

После раздела «Почему cuda_setup.py» добавить короткий раздел:

```markdown
## Intel iGPU/NPU (OpenVINO) — заметка

На машинах без NVIDIA `auto` выбирает Intel-графику через OpenVINO GenAI:
готовые int8-модели качаются с HF (`OpenVINO/whisper-*-int8-ov`), первая
загрузка компилирует модель под конкретный GPU (десятки секунд, дальше —
кэш в `ov_cache/`). VAD работает (Silero из faster-whisper), фильтры
галлюцинаций работают; `min_language_probability` в этом пути НЕ действует
(движок не сообщает уверенность в языке). Бенч скорости: `python
bench_backends.py record`, затем `run` (см. bench_results.md).
```

- [ ] **Step 3: Полный прогон тестов + ручной смоук**

```bash
.venv/Scripts/python.exe test_backends.py && \
.venv/Scripts/python.exe test_paths.py && \
.venv/Scripts/python.exe test_postprocess.py && \
.venv/Scripts/python.exe smoke_gui.py
```

Expected: всё зелёное. Затем живой прогон `gui.py` (пользователь): полный цикл диктовки на iGPU — короткая и длинная фразы, термины из словаря, пустая запись (тишина → «(пусто)», не галлюцинация).

- [ ] **Step 4: Commit**

```bash
git add README.md requirements.txt requirements.lock.txt
git commit -m "docs: OpenVINO iGPU path in README; pin openvino-genai"
```

---

## Self-Review (выполнен при написании)

- **Spec coverage:** OpenVINOBackend+VAD+адаптер (Task 6 — спека A), карта моделей и подстановка (Task 6/7 — B), конфиг+маршрутизация (Task 7 — C), model_store (Task 5 — D), UI (Task 8 — E), зависимости (Task 1/9 — F), порядок работ 1-6 спеки = Task 1,2-3,4,5-8,9. Ошибки: ValueError понятным текстом (Task 6), фолбэк auto→cpu (Task 7, авто-цепочка), возобновляемая докачка (Task 5, snapshot_download + маркер после успеха). NPU: опция устройства + STATIC_PIPELINE (Task 6/8), не дефолт.
- **Placeholders:** нет TBD; значение `IGPU_AUTO_SUBSTITUTE` параметризовано воротами Task 4 с явным источником (bench_results.md) и дефолтом в коде; версия openvino-genai — фактическая с машины (иначе пришлось бы гадать).
- **Type consistency:** `OpenVINOBackend(model=, device=)` единообразно в Task 6/7; `ensure_downloaded(model, kind=, on_progress=)` в Task 5 и вызове dictate.py; `resolve_runtime(..., ov_gpu_available=False)` обратно-совместим со старыми вызовами в существующих тестах.
