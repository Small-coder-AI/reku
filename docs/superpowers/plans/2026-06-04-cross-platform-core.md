# План 1 — Кросс-платформенное ядро whisper_ptt

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать движок переносимым: авто-детект железа (CUDA→GPU, иначе→CPU) за единой абстракцией бэкенда, конфиг и кэш модели во frozen-безопасном месте, скачивание модели при первом запуске, защита от второго инстанса, отображение устройства в UI и заглушки под OpenVINO/API (Фаза 2).

**Architecture:** Вводим `backends.py` с абстракцией `Backend` и чистой функцией `resolve_runtime()`; текущая логика faster-whisper переезжает в `CTranslate2Backend`. `DictationApp` больше не держит `WhisperModel` напрямую — он работает через `self.backend`. Пути (конфиг, модели) централизуются в `config.data_dir()` и `model_store.py`. Политика (порог language_probability, постпроцессинг) остаётся в `DictationApp.transcribe` — она одинакова для всех бэкендов.

**Tech Stack:** Python 3.13, faster-whisper / CTranslate2, PySide6 (+ QtNetwork для single-instance), numpy. Тесты — простые скрипты в стиле проекта (`python test_*.py`, хелпер `check()`, `SystemExit`), без pytest и без GPU.

---

## Структура файлов

**Создаём:**
- `model_store.py` — где лежат модели и как их докачивать (чистые пути + докачка).
- `backends.py` — абстракция `Backend`, `resolve_runtime()`, `CTranslate2Backend`, заглушки `OpenVINOBackend`/`ApiBackend`, `select_backend()`.
- `test_paths.py` — тесты `config.data_dir()` и `model_store.model_path()`.
- `test_backends.py` — тесты `resolve_runtime()` и маршрутизации `select_backend()`.
- `test_transcribe_pipeline.py` — тест `DictationApp.transcribe` на фейковом бэкенде (без GPU).

**Меняем:**
- `config.py` — `data_dir()`, дефолты `device="auto"`/`compute_type="auto"`, зарезервированные API-поля.
- `dictate.py` — `DictationApp` работает через `self.backend`; состояние `downloading`.
- `gui_theme.py` — состояние `downloading` в `STATE_RGB`/`STATE_TEXT`.
- `gui.py` — комбобокс «Устройство» (Авто/CUDA/CPU/API-заглушка), показ устройства в подсказке + уведомление о фолбэке, поле «Словарь терминов», single-instance через `QLocalServer`.
- `selftest_pipeline.py` — обновить под новый API (`app.backend`).

---

## Task 1: `config.py` — frozen-безопасные пути и новые поля

**Files:**
- Modify: `config.py`
- Test: `test_paths.py` (создаём в этой задаче)

- [ ] **Step 1: Написать падающий тест `test_paths.py`**

```python
"""Тесты путей. Запуск: python test_paths.py (GPU не нужен)."""
import os
import sys


def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    return cond


ok = True

import config

# data_dir() из исходников == каталог config.py
expected_src = os.path.dirname(os.path.abspath(config.__file__))
ok &= check("data_dir из исходников = каталог скрипта", config.data_dir() == expected_src)

# data_dir() во frozen-режиме = %APPDATA%\whisper_ptt
sys.frozen = True
try:
    d = config.data_dir()
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    ok &= check("data_dir frozen = %APPDATA%\\whisper_ptt",
                d == os.path.join(appdata, "whisper_ptt"))
finally:
    del sys.frozen

# новые дефолты конфига
c = config.Config()
ok &= check("device дефолт = auto", c.device == "auto")
ok &= check("compute_type дефолт = auto", c.compute_type == "auto")
ok &= check("api поля присутствуют",
            hasattr(c, "api_provider") and hasattr(c, "api_base_url")
            and hasattr(c, "api_key") and hasattr(c, "api_model"))

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.\.venv\Scripts\python.exe test_paths.py`
Expected: FAIL (`config.data_dir` не существует / дефолты ещё `cuda`/`float16`), `ЕСТЬ ПАДЕНИЯ`, код выхода 1.

- [ ] **Step 3: Внести изменения в `config.py`**

Заменить шапку с импортами и `CONFIG_PATH` (строки 7–11):

```python
import os
import sys
import json
from dataclasses import dataclass, asdict, fields


def data_dir() -> str:
    """Каталог данных приложения. Чистая функция (без побочных эффектов).
    Frozen (.exe): %APPDATA%\\whisper_ptt — из Program Files писать нельзя.
    Из исходников: каталог этого файла (удобно для разработки)."""
    if getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(appdata, "whisper_ptt")
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_PATH = os.path.join(data_dir(), "config.json")
```

В датаклассе `Config` заменить поля устройства (строки 18–20 оригинала):

```python
    # ── модель ───────────────────────────────────────────────
    model: str = "large-v3"          # large-v3 / medium / small / ... или путь
    device: str = "auto"             # auto / cuda / cpu / api
    compute_type: str = "auto"       # auto / float16 / int8_float16 / int8 / float32
```

Добавить зарезервированные API-поля сразу после блока «модель» (перед блоком «ввод»):

```python
    # ── API-бэкенд (зарезервировано, реализация в Фазе 2) ────
    api_provider: str = "openrouter"
    api_base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = ""
    api_model: str = ""
```

В `save()` гарантировать существование каталога — заменить тело функции:

```python
def save(cfg: Config, path: str = CONFIG_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `.\.venv\Scripts\python.exe test_paths.py`
Expected: все строки `OK`, `ВСЕ ПРОШЛИ`, код выхода 0.

- [ ] **Step 5: Коммит**

```bash
git add config.py test_paths.py
git commit -m "feat(config): frozen-безопасный data_dir() + device/compute auto + резерв API-полей"
```

---

## Task 2: `model_store.py` — место хранения и докачка моделей

**Files:**
- Create: `model_store.py`
- Test: `test_paths.py` (дополняем)

- [ ] **Step 1: Дописать падающие проверки в `test_paths.py`**

Вставить перед строкой `print("\nИТОГ:" ...)`:

```python
# model_store: пути считаются от config.data_dir() (монкипатчим на temp)
import tempfile
import model_store

_tmp = tempfile.mkdtemp()
config.data_dir = lambda: _tmp  # монкипатч источника правды путей
ok &= check("model_cache_dir = data_dir/models",
            model_store.model_cache_dir() == os.path.join(_tmp, "models"))
ok &= check("model_path безопасит '/'",
            model_store.model_path("Systran/faster-whisper-small")
            == os.path.join(_tmp, "models", "Systran_faster-whisper-small"))
ok &= check("is_cached=False для несуществующей",
            model_store.is_cached("small") is False)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.\.venv\Scripts\python.exe test_paths.py`
Expected: FAIL с `ModuleNotFoundError: No module named 'model_store'`.

- [ ] **Step 3: Создать `model_store.py`**

```python
"""Где лежат модели faster-whisper и как их докачивать.

Источник правды по путям — config.data_dir() (импортируется лениво, чтобы
тесты могли его подменить). Модель кладётся в плоский каталог data_dir/models/<имя>
и грузится из него по локальному пути — это надёжнее между версиями faster-whisper,
чем зависеть от HF-кэша и kwarg'ов вроде cache_dir.
"""
import os


def _data_dir() -> str:
    import config           # лениво: тесты подменяют config.data_dir
    return config.data_dir()


def model_cache_dir() -> str:
    """Каталог с моделями (создаётся при обращении)."""
    d = os.path.join(_data_dir(), "models")
    os.makedirs(d, exist_ok=True)
    return d


def model_path(model: str) -> str:
    """Локальный каталог конкретной модели. '/' в id заменяется на '_'."""
    return os.path.join(model_cache_dir(), model.replace("/", "_"))


def is_cached(model: str) -> bool:
    """Скачана ли модель (есть ли model.bin в её каталоге)."""
    return os.path.isfile(os.path.join(model_path(model), "model.bin"))


def ensure_downloaded(model: str, on_progress=None) -> str:
    """Гарантирует наличие модели локально. Возвращает путь к ней.
    on_progress(model) зовётся один раз перед началом скачивания (для UI)."""
    p = model_path(model)
    if is_cached(model):
        return p
    if on_progress:
        on_progress(model)
    from faster_whisper.utils import download_model
    download_model(model, output_dir=p)
    return p
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `.\.venv\Scripts\python.exe test_paths.py`
Expected: все `OK`, `ВСЕ ПРОШЛИ`, код выхода 0.

- [ ] **Step 5: Коммит**

```bash
git add model_store.py test_paths.py
git commit -m "feat(model_store): плоский каталог моделей в data_dir + докачка при первом запуске"
```

---

## Task 3: `backends.py` — абстракция, авто-детект, заглушки

**Files:**
- Create: `backends.py`
- Test: `test_backends.py`

- [ ] **Step 1: Написать падающий тест `test_backends.py`**

```python
"""Тесты бэкендов. Запуск: python test_backends.py (GPU не нужен)."""
import backends
from backends import resolve_runtime, select_backend, CTranslate2Backend, \
    OpenVINOBackend, ApiBackend
from types import SimpleNamespace as S


def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    return cond


ok = True

# resolve_runtime: auto + есть CUDA -> cuda/float16, модель не трогаем
ok &= check("auto+cuda -> cuda/float16/large-v3",
            resolve_runtime("auto", "auto", "large-v3", cuda_available=True)
            == ("cuda", "float16", "large-v3"))

# auto + нет CUDA + тяжёлая модель -> cpu/int8/small (понижение)
ok &= check("auto+no-cuda+heavy -> cpu/int8/small",
            resolve_runtime("auto", "auto", "large-v3", cuda_available=False)
            == ("cpu", "int8", "small"))

# auto + нет CUDA + лёгкая модель -> остаётся как есть
ok &= check("auto+no-cuda+light -> cpu/int8/base",
            resolve_runtime("auto", "auto", "base", cuda_available=False)
            == ("cpu", "int8", "base"))

# явный cpu НЕ понижает модель (это решение пользователя)
ok &= check("явный cpu не понижает модель",
            resolve_runtime("cpu", "auto", "large-v3", cuda_available=False)
            == ("cpu", "int8", "large-v3"))

# явный cuda + явный compute -> без изменений
ok &= check("явный cuda+float16",
            resolve_runtime("cuda", "float16", "medium", cuda_available=True)
            == ("cuda", "float16", "medium"))

# select_backend: device=api -> ApiBackend (заглушка), .load() кидает NotImplementedError
cfg_api = S(device="api", compute_type="auto", model="small")
b = select_backend(cfg_api)
ok &= check("api -> ApiBackend", isinstance(b, ApiBackend))
try:
    b.load()
    ok &= check("ApiBackend.load кидает NotImplementedError", False)
except NotImplementedError:
    ok &= check("ApiBackend.load кидает NotImplementedError", True)

# select_backend: локальный путь -> CTranslate2Backend с разрешённым устройством
cfg_loc = S(device="auto", compute_type="auto", model="large-v3")
b2 = select_backend(cfg_loc, cuda_probe=lambda: False)
ok &= check("auto+no-cuda -> CTranslate2Backend/cpu",
            isinstance(b2, CTranslate2Backend) and b2.device == "cpu"
            and b2.model_id == "small")
ok &= check("device_label для cpu", b2.device_label == "CPU")

# OpenVINOBackend.load -> NotImplementedError
try:
    OpenVINOBackend(S()).load()
    ok &= check("OpenVINOBackend.load кидает NotImplementedError", False)
except NotImplementedError:
    ok &= check("OpenVINOBackend.load кидает NotImplementedError", True)

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.\.venv\Scripts\python.exe test_backends.py`
Expected: FAIL с `ModuleNotFoundError: No module named 'backends'`.

- [ ] **Step 3: Создать `backends.py`**

```python
"""Абстракция бэкенда инференса + авто-детект железа.

Сейчас реализован один локальный бэкенд (CTranslate2/faster-whisper).
OpenVINOBackend (Intel iGPU/NPU) и ApiBackend (OpenRouter/OpenAI/…) — заглушки,
реализуются в Фазе 2. Все бэкенды возвращают из transcribe() одинаковый
(segments, info), поэтому UI и постпроцессинг не зависят от источника.

ВАЖНО про порядок импорта: faster_whisper грузится ЛЕНИВО внутри
CTranslate2Backend.load(), и строго после cuda_setup (тот кладёт nvidia-DLL в PATH).
"""
from abc import ABC, abstractmethod

# Тяжёлые модели, которые на CPU слишком медленные — в auto-режиме понижаем до small.
HEAVY_MODELS = {
    "large", "large-v1", "large-v2", "large-v3", "large-v3-turbo", "turbo",
    "distil-large-v2", "distil-large-v3", "distil-large-v3.5",
}
CPU_FALLBACK_MODEL = "small"


def _cuda_available() -> bool:
    """Есть ли пригодный CUDA-GPU для CTranslate2. Любой сбой = нет GPU."""
    try:
        import cuda_setup            # noqa: F401 — кладёт nvidia-DLL в PATH
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def resolve_runtime(device, compute_type, model, *, cuda_available):
    """Чистая функция: ('auto'|'cuda'|'cpu', compute, model) -> конкретные значения.
    Понижение тяжёлой модели до small происходит ТОЛЬКО в auto-режиме при фолбэке на CPU."""
    auto = (device == "auto")
    dev = ("cuda" if cuda_available else "cpu") if auto else device

    comp = compute_type
    if comp in ("", "auto", None):
        comp = "float16" if dev == "cuda" else "int8"

    mdl = model
    if auto and dev == "cpu" and model in HEAVY_MODELS:
        mdl = CPU_FALLBACK_MODEL

    return dev, comp, mdl


class Backend(ABC):
    """Контракт бэкенда. load() грузит модель; transcribe() отдаёт (segments, info)."""
    name = "base"

    @property
    @abstractmethod
    def device_label(self) -> str:
        """Человекочитаемое устройство для UI, напр. 'GPU (CUDA)' / 'CPU'."""

    @property
    def model_id(self):
        """ID модели для докачки, либо None если докачка не нужна (напр. API)."""
        return None

    @abstractmethod
    def load(self):
        ...

    @abstractmethod
    def transcribe(self, audio, cfg):
        ...


class CTranslate2Backend(Backend):
    """Локальный инференс через faster-whisper (CPU или NVIDIA-CUDA)."""
    name = "ctranslate2"

    def __init__(self, model, device, compute_type):
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self._model = None

    @property
    def device_label(self) -> str:
        return "GPU (CUDA)" if self.device == "cuda" else "CPU"

    @property
    def model_id(self):
        return self.model_name

    def load(self):
        import cuda_setup            # noqa: F401 — строго до faster_whisper
        from faster_whisper import WhisperModel
        import model_store
        src = self.model_name
        if model_store.is_cached(self.model_name):
            src = model_store.model_path(self.model_name)
        self._model = WhisperModel(src, device=self.device,
                                   compute_type=self.compute_type)

    def transcribe(self, audio, cfg):
        return self._model.transcribe(
            audio,
            language=cfg.lang_or_none,
            beam_size=cfg.beam_size,
            vad_filter=cfg.vad_filter,
            initial_prompt=cfg.initial_prompt,
            condition_on_previous_text=cfg.condition_on_previous_text,
            no_repeat_ngram_size=cfg.no_repeat_ngram_size,
        )


class OpenVINOBackend(Backend):
    """Intel iGPU/NPU через OpenVINO. Заглушка — реализация в Фазе 2."""
    name = "openvino"

    def __init__(self, cfg):
        self.cfg = cfg

    @property
    def device_label(self) -> str:
        return "Intel (OpenVINO)"

    def load(self):
        raise NotImplementedError("OpenVINO-бэкенд — Фаза 2 (на ноуте Honor)")

    def transcribe(self, audio, cfg):
        raise NotImplementedError("OpenVINO-бэкенд — Фаза 2 (на ноуте Honor)")


class ApiBackend(Backend):
    """Облачный провайдер (OpenRouter/OpenAI/…). Заглушка — реализация в Фазе 2."""
    name = "api"

    def __init__(self, cfg):
        self.cfg = cfg

    @property
    def device_label(self) -> str:
        return "API (облако)"

    def load(self):
        raise NotImplementedError("API-бэкенд — Фаза 2 (опт-ин, аудио уходит в облако)")

    def transcribe(self, audio, cfg):
        raise NotImplementedError("API-бэкенд — Фаза 2 (опт-ин, аудио уходит в облако)")


def select_backend(cfg, *, cuda_probe=None):
    """Маршрутизация: cfg.device -> конкретный Backend (ещё не загружен)."""
    if cfg.device == "api":
        return ApiBackend(cfg)
    probe = cuda_probe or _cuda_available
    dev, comp, mdl = resolve_runtime(cfg.device, cfg.compute_type, cfg.model,
                                     cuda_available=probe())
    return CTranslate2Backend(model=mdl, device=dev, compute_type=comp)
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `.\.venv\Scripts\python.exe test_backends.py`
Expected: все `OK`, `ВСЕ ПРОШЛИ`, код выхода 0.

- [ ] **Step 5: Коммит**

```bash
git add backends.py test_backends.py
git commit -m "feat(backends): абстракция Backend + resolve_runtime + CTranslate2 + заглушки OpenVINO/Api"
```

---

## Task 4: `dictate.py` — `DictationApp` через бэкенд + состояние `downloading`

**Files:**
- Modify: `dictate.py`
- Test: `test_transcribe_pipeline.py`

- [ ] **Step 1: Написать падающий тест `test_transcribe_pipeline.py`**

```python
"""Тест политики transcribe (порог языка + постпроцессинг) на фейковом бэкенде.
GPU не нужен. Запуск: python test_transcribe_pipeline.py"""
import numpy as np
from types import SimpleNamespace as S
import config
from dictate import DictationApp


def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    return cond


def seg(text, cr=1.0):
    return S(text=text, compression_ratio=cr)


class FakeBackend:
    device_label = "CPU"
    model_id = None
    def __init__(self, segments, lang="ru", lang_p=0.9):
        self._segs = segments
        self._info = S(language=lang, language_probability=lang_p)
    def load(self):
        pass
    def transcribe(self, audio, cfg):
        return iter(self._segs), self._info


ok = True
audio = np.zeros(16000, dtype=np.float32)

# нормальная речь проходит, фантом вырезается
cfg = config.Config(min_language_probability=0.0)
app = DictationApp(cfg)
app.backend = FakeBackend([seg("привет мир"), seg("Thank you for watching!")])
ok &= check("текст распознан, фантом вырезан", app.transcribe(audio) == "привет мир")

# низкая вероятность языка -> подавление (пусто)
cfg2 = config.Config(min_language_probability=0.5)
app2 = DictationApp(cfg2)
app2.backend = FakeBackend([seg("привет")], lang_p=0.2)
ok &= check("низкий language_probability -> пусто", app2.transcribe(audio) == "")

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.\.venv\Scripts\python.exe test_transcribe_pipeline.py`
Expected: FAIL — `app.backend` пока не используется (`transcribe` зовёт несуществующий `self.model`), либо `AttributeError`.

- [ ] **Step 3: Изменить `dictate.py`**

В `__init__` заменить строку `self.model = None` (строка 54) на:

```python
        self.backend = None
```

Добавить в кортеж `STATES` (строка 48) состояние `downloading`:

```python
    STATES = ("loading", "downloading", "idle", "recording", "transcribing")
```

Заменить весь метод `load_model` (строки 85–93) на:

```python
    # ── загрузка модели ──────────────────────────────────────
    def load_model(self):
        import backends
        import model_store
        self.backend = backends.select_backend(self.cfg)
        mid = self.backend.model_id
        if mid and not model_store.is_cached(mid):
            self._set_state("downloading")
            model_store.ensure_downloaded(
                mid, on_progress=lambda m: print(
                    f"Скачиваю модель '{m}' (первый запуск, может занять минуты)…",
                    flush=True))
        self._set_state("loading")
        t0 = time.perf_counter()
        self.backend.load()
        print(f"Модель '{mid or self.backend.name}' на {self.backend.device_label} "
              f"за {time.perf_counter() - t0:.1f} c.", flush=True)
        self._set_state("idle")
```

В методе `transcribe` заменить вызов модели (строки 143–151) — было `segments, info = self.model.transcribe(...)` с kwargs — на делегирование бэкенду:

```python
        segments, info = self.backend.transcribe(audio, c)
```

Заменить тело `reload_model` (строки 252–257) — `self.model = None` на `self.backend = None`:

```python
    def reload_model(self):
        """Перезагрузка модели (после смены model/device/compute). Зови в фоне."""
        with self._lock:
            if self._recording or self._transcribing:
                return False
            self.backend = None
        self.load_model()
        return True
```

В `start()` заменить условие `if self.model is None:` (строка 223) на:

```python
        if self.backend is None:
```

Удалить из шапки комментарий про ленивый импорт faster_whisper в load_model (строки 28–30) — он теперь живёт в `backends.py`; заменить на короткую заметку:

```python
# Инференс инкапсулирован в backends.py (faster_whisper грузится лениво там,
# строго после cuda_setup). DictationApp работает через self.backend.
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `.\.venv\Scripts\python.exe test_transcribe_pipeline.py`
Expected: все `OK`, `ВСЕ ПРОШЛИ`, код выхода 0.

- [ ] **Step 5: Прогнать существующий регресс постпроцессинга**

Run: `.\.venv\Scripts\python.exe test_postprocess.py`
Expected: `ВСЕ ПРОШЛИ` (мы его не трогали — проверяем, что ничего не сломалось).

- [ ] **Step 6: Коммит**

```bash
git add dictate.py test_transcribe_pipeline.py
git commit -m "refactor(dictate): DictationApp через Backend + состояние downloading"
```

---

## Task 5: `gui_theme.py` — состояние `downloading`

**Files:**
- Modify: `gui_theme.py`

- [ ] **Step 1: Добавить состояние в обе карты**

В `STATE_RGB` (после строки `"loading": RGB["dim"],`) добавить:

```python
    "downloading":  RGB["busy"],
```

В `STATE_TEXT` (после строки `"loading": "Загрузка модели…",`) добавить:

```python
    "downloading":  "Скачиваю модель…",
```

- [ ] **Step 2: Проверить, что тема импортируется без ошибок**

Run: `.\.venv\Scripts\python.exe -c "import gui_theme; print(gui_theme.STATE_TEXT['downloading'])"`
Expected: вывод `Скачиваю модель…`, без трейсбэка.

- [ ] **Step 3: Коммит**

```bash
git add gui_theme.py
git commit -m "feat(theme): состояние downloading (цвет + подпись)"
```

---

## Task 6: `gui.py` — устройство в UI, словарь, single-instance

**Files:**
- Modify: `gui.py`
- Проверка: ручная (нужен GUI-сеанс) — отдельный шаг с чек-листом.

- [ ] **Step 1: Импорт QtNetwork и константа single-instance**

В блоке импортов PySide6 (после строки `from PySide6.QtWidgets import (...)`, ~строка 18) добавить:

```python
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_SINGLE_KEY = "whisper_ptt_singleton"
```

- [ ] **Step 2: Комбобокс устройств — пары (label, value) + пункт API**

Заменить строку `DEVICES = ["cuda", "cpu"]` (строка 26) на:

```python
DEVICES = [("Авто", "auto"), ("GPU (CUDA)", "cuda"), ("CPU", "cpu"),
           ("API (облако)", "api")]
```

В `_build_settings_page` заменить создание `device_combo` (строки 196–197) на построение через data + отключение пункта API (заглушка-«место»):

```python
        self.device_combo = QComboBox()
        for label, val in DEVICES:
            self.device_combo.addItem(label, val)
        self._select_data(self.device_combo, self.cfg.device)
        # «API (облако)» — зарезервированное место (Фаза 2): видно, но неактивно
        _api_i = self.device_combo.findData("api")
        if _api_i >= 0:
            self.device_combo.model().item(_api_i).setEnabled(False)
```

- [ ] **Step 3: `_apply_settings` — читать device по data, не по тексту**

В `_apply_settings` заменить строку `c.device = self.device_combo.currentText()` (строка 295) на:

```python
        c.device = self.device_combo.currentData()
```

- [ ] **Step 4: Поле «Словарь терминов» (initial_prompt) в настройках**

В `_build_settings_page`, в секцию «РАСПОЗНАВАНИЕ» — после строк с `self.vad_chk` / `self.halluc_chk` и перед `lay.addStretch(1)` (после строки 224) добавить:

```python
        self.vocab_edit = QLineEdit()
        self.vocab_edit.setText(self.cfg.initial_prompt)
        self.vocab_edit.setPlaceholderText("термины через запятую (помогают распознаванию)")
        lay.addWidget(_row("Словарь", self.vocab_edit))
```

В `_apply_settings` (после `c.drop_hallucinations = self.halluc_chk.isChecked()`, строка 300) добавить сохранение:

```python
        c.initial_prompt = self.vocab_edit.text().strip()
```

- [ ] **Step 5: Показ устройства в подсказке + уведомление о фолбэке**

Заменить метод `_update_hint` (строки 245–249) на:

```python
    def _update_hint(self):
        names = {v: l for l, v in HOTKEYS}
        key = names.get(self.cfg.hotkey, self.cfg.hotkey)
        mode = "PTT" if self.cfg.mode == "ptt" else "Toggle"
        dev = ""
        b = getattr(self.engine, "backend", None) if self.engine else None
        if b is not None:
            label = b.device_label
            if self.cfg.device == "auto" and getattr(b, "device", None) == "cpu":
                label = "CPU (GPU не найден)"
            dev = " · " + label
        self.hint.setText(f"{key} · {mode}{dev}")
```

В `set_state` обновлять подсказку при переходе в `idle` — в конце метода `set_state` (после строки `self.rec_btn.setEnabled(not busy)`, строка 264) добавить:

```python
        if state == "idle":
            self._update_hint()
```

- [ ] **Step 6: Single-instance в `main()`**

Сразу после строк `app = QApplication(sys.argv)` и `app.setQuitOnLastWindowClosed(False)` (строки 345–346) вставить проверку до создания движка (чтобы не грузить вторую модель):

```python
    # single-instance: если уже запущено — показать то окно и выйти
    _probe = QLocalSocket()
    _probe.connectToServer(_SINGLE_KEY)
    if _probe.waitForConnected(200):
        _probe.write(b"show"); _probe.flush(); _probe.waitForBytesWritten(300)
        sys.exit(0)
    QLocalServer.removeServer(_SINGLE_KEY)
    _server = QLocalServer()
    _server.listen(_SINGLE_KEY)
```

После создания `win` (после строки `win = MainWindow(cfg, engine=engine, bridge=bridge)`, строка 356) подключить обработчик повторного запуска:

```python
    def _on_second_instance():
        conn = _server.nextPendingConnection()
        if conn is not None:
            conn.readyRead.connect(lambda: (conn.readAll(), win.show_normal()))
    _server.newConnection.connect(_on_second_instance)
```

- [ ] **Step 7: Смоук-импорт (без запуска цикла)**

Run: `.\.venv\Scripts\python.exe -c "import gui; print('gui import OK')"`
Expected: `gui import OK`, без трейсбэка (проверяет синтаксис и импорт QtNetwork).

- [ ] **Step 8: Ручная проверка (нужен GUI-сеанс)**

Запусти: `.\.venv\Scripts\python.exe gui.py`
Проверь и отметь:
- окно открывается, модель грузится, в подсказке под статусом видно устройство (напр. `Right Ctrl · PTT · GPU (CUDA)`);
- настройки: в «Устройство» есть Авто/GPU/CPU и неактивный «API (облако)»; поле «Словарь» заполнено `initial_prompt`;
- меняешь язык/режим/словарь → «Применить» → сохраняется (проверь `config.json` в каталоге проекта);
- второй запуск `gui.py` из другого терминала — НЕ грузит вторую модель, а показывает уже открытое окно.

- [ ] **Step 9: Коммит**

```bash
git add gui.py
git commit -m "feat(gui): устройство в подсказке, поле словаря, пункт API-заглушки, single-instance"
```

---

## Task 7: `selftest_pipeline.py` — обновить под новый API

**Files:**
- Modify: `selftest_pipeline.py`

- [ ] **Step 1: Обновить вывод устройства под бэкенд**

Заменить блок «2. модель + пайплайн» (строки 15–17) на:

```python
# 2. модель + пайплайн
app = DictationApp(cfg)
app.load_model()
print("backend:", app.backend.name, "| device:", app.backend.device_label)
```

- [ ] **Step 2: Прогнать headless-селфтест (нужен GPU/модель, реальный инференс)**

Run: `.\.venv\Scripts\python.exe selftest_pipeline.py`
Expected: печатает `backend: ctranslate2 | device: GPU (CUDA)` (на этом ПК), затем `[silence] -> ''` и `[noise] -> ''`, и `OK: пайплайн отработал без исключений.` без трейсбэка.

- [ ] **Step 3: Прогнать весь набор тестов разом**

Run:
```powershell
.\.venv\Scripts\python.exe test_paths.py; `
.\.venv\Scripts\python.exe test_backends.py; `
.\.venv\Scripts\python.exe test_transcribe_pipeline.py; `
.\.venv\Scripts\python.exe test_postprocess.py
```
Expected: каждый скрипт печатает `ВСЕ ПРОШЛИ`.

- [ ] **Step 4: Коммит**

```bash
git add selftest_pipeline.py
git commit -m "test(selftest): печать backend/device под новый API"
```

---

## Self-Review (выполнено при написании плана)

**1. Покрытие спецификации (Фаза 1, блоки A/B + словарь из D):**
- Абстракция бэкенда + детект + понижение модели → Task 3 (+ Task 4 проводку).
- `OpenVINOBackend`/`ApiBackend` заглушки + резерв API-полей конфига → Task 1, Task 3.
- `device="auto"`/`compute="auto"` + UI «Авто»/«API» + показ устройства + фолбэк-уведомление → Task 1, Task 6.
- Конфиг/данные/кэш в `%APPDATA%` (frozen) → Task 1, Task 2.
- Скачивание модели при первом запуске (состояние `downloading`) → Task 2, Task 4, Task 5.
- Защита от второго инстанса → Task 6.
- Поле «Словарь терминов» (фича из D) → Task 6.
- **Намеренно НЕ в этом плане (отдельные планы):** упаковка .exe/PyInstaller/cuda_setup-frozen/автозапуск/ярлык (План 2); звук старт/стоп и история диктовок (План 3).

**2. Плейсхолдеры:** не найдено — в каждом шаге полный код/команда/ожидаемый вывод.

**3. Консистентность типов:** `Backend.device_label`/`model_id`/`load`/`transcribe`, `resolve_runtime(device, compute_type, model, *, cuda_available)`, `select_backend(cfg, *, cuda_probe=)`, `config.data_dir()`, `model_store.{model_cache_dir,model_path,is_cached,ensure_downloaded}`, `DictationApp.backend` — имена совпадают во всех задачах и тестах.
