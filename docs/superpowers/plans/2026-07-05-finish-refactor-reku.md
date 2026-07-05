# Финишный рефакторинг: мердж Фазы 1 + Reku + структура + install.ps1 — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Вернуть в main неслитую июньскую работу (темы/галочки/exe/надёжность/фикс латиницы), переименовать продукт в Reku, разложить репозиторий по папкам и сделать установку одной командой PowerShell.

**Architecture:** Пять последовательных фаз: (A) мердж ветки `origin/feature/desktop-reliability-ui-installer` в main с ручным разрешением 3 конфликтов; (B) переименование в Reku + пакетная структура `reku/` + миграция каталога данных; (C) `install.ps1` — bootstrapper с детектом железа; (D) видимость рантайма в UI; (E) README/LICENSE/уборка. Порядок жёсткий: перемещение файлов до мерджа запрещено.

**Tech Stack:** Python 3.12, PySide6, faster-whisper/CTranslate2, OpenVINO GenAI, PyInstaller, Inno Setup, PowerShell 5.1+.

**Спека:** `docs/superpowers/specs/2026-07-05-finish-refactor-reku-design.md`

## Global Constraints

- Язык кода/коммитов: идентификаторы и commit-сообщения — английские, комментарии/док-строки/UI-строки — русские.
- `cuda_setup` импортируется СТРОГО до `faster_whisper` (везде, включая новую структуру).
- Имя продукта: **Reku** (exe `Reku.exe`, каталог данных `%APPDATA%\Reku`, установка `%LOCALAPPDATA%\Programs\Reku`, репозиторий `Small-coder-AI/reku`).
- Публикация репозитория (private → public) — ВНЕ этого плана, только по явной команде Руслана.
- Тестовая команда: `.venv/Scripts/python.exe -m pytest <файлы> -v` из корня репо (после Фазы B тесты лежат в `tests/`).
- Каждая задача заканчивается зелёными тестами и коммитом.

---

## Фаза A: мердж ветки Фазы 1 в main

Контекст для исполнителя. Merge-base: `960cb16`. Со стороны main (13 коммитов) — OpenVINO iGPU (Фаза 2). Со стороны ветки (6 коммитов) — темы/надёжность/exe (Фаза 1). `git merge-tree` подтвердил: конфликтуют ровно 3 файла — `model_store.py`, `dictate.py`, `gui.py`. Остальные общие файлы (`.gitignore`, `README.md`, `backends.py`, `config.py`, `requirements*.txt`, `test_backends.py`) сливаются автоматически. `gui_theme.py` в main не менялся после base → целиком придёт из ветки (там уже есть состояния `downloading` и `error` во всех темах).

### Task 1: Запуск мерджа + разрешение model_store.py

**Files:**
- Modify: `model_store.py` (разрешение конфликта)

**Interfaces:**
- Produces: `is_cached(model) -> bool`; `ensure_downloaded(model, kind="ct2", on_progress=None) -> str` — сигнатура main-стороны сохраняется, потребители: `dictate._download_and_load`, `backends.CTranslate2Backend.load`.

- [ ] **Step 1: Создать рабочую ветку и запустить мердж**

```bash
git checkout -b merge/phase1-desktop
git merge origin/feature/desktop-reliability-ui-installer
# Ожидаемо: CONFLICT (content) в dictate.py, gui.py, model_store.py; auto-merge остальных
git status --short   # UU dictate.py, UU gui.py, UU model_store.py
```

- [ ] **Step 2: Записать целевой model_store.py (совмещение обеих сторон)**

Логика совмещения: от ветки — `_dir_complete` (полный набор файлов CT2) и атомарная докачка через `.tmp` + `os.replace`; от main — параметр `kind` и OV-путь (`snapshot_download` + маркер). `is_cached` считает модель готовой, если каталог полон по-CT2 ЛИБО стоит OV-маркер. Итоговое содержимое секций файла (шапку до `model_path` включительно не трогать — она без конфликта):

```python
# Полный набор: модель грузится несколькими файлами. Проверяем не только model.bin,
# иначе ОБОРВАННАЯ докачка (есть model.bin, нет токенайзера) сочтётся «скачано» и
# WhisperModel упадёт при загрузке → UI зависнет в loading (см. dictate.load_model).
_REQUIRED = ("model.bin", "config.json")
_TOKENIZERS = ("tokenizer.json", "vocabulary.json", "vocabulary.txt")

_OV_MARKER = ".download_complete"


def _dir_complete(d: str) -> bool:
    """В каталоге d лежит полный набор файлов CT2-модели (а не оборванная докачка):
    model.bin, config.json и хотя бы один файл токенайзера."""
    if not all(os.path.isfile(os.path.join(d, f)) for f in _REQUIRED):
        return False
    return any(os.path.isfile(os.path.join(d, t)) for t in _TOKENIZERS)


def is_cached(model: str) -> bool:
    """Скачана ли модель ПОЛНОСТЬЮ: полный набор CT2-файлов либо маркер OV.
    Для OV маркер надёжнее перечня файлов — состав репо может меняться."""
    p = model_path(model)
    return _dir_complete(p) or os.path.isfile(os.path.join(p, _OV_MARKER))


def ensure_downloaded(model: str, kind: str = "ct2", on_progress=None) -> str:
    """Гарантирует наличие модели локально. kind: 'ct2' (faster-whisper, атомарная
    докачка через .tmp) или 'ov' (репо OpenVINO с HF; snapshot_download сам
    возобновляем, маркер пишем в конце). on_progress(model) зовётся один раз
    перед началом скачивания (для UI)."""
    p = model_path(model)
    if is_cached(model):
        return p
    if on_progress:
        on_progress(model)
    if kind == "ov":
        from huggingface_hub import snapshot_download
        snapshot_download(model, local_dir=p)
        open(os.path.join(p, _OV_MARKER), "w").close()
        return p
    import shutil
    from faster_whisper.utils import download_model
    tmp = p + ".tmp"
    # прошлый запуск мог докачать модель в .tmp, но не суметь переименовать (каталог p
    # был занят другим процессом). Тогда повторно НЕ качаем 3 ГБ — берём готовый .tmp.
    if not _dir_complete(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
        download_model(model, output_dir=tmp)
    shutil.rmtree(p, ignore_errors=True)   # убрать возможный неполный прежний
    if os.path.exists(p):
        # Windows: rmtree(ignore_errors=True) молча не удалил заблокированный каталог.
        # НЕ трогаем готовый .tmp (модель уже скачана) — os.replace всё равно упал бы;
        # переименуем при следующем запуске, когда блокировка снимется.
        raise OSError(
            f"не удалось убрать старый каталог модели (занят другим процессом?): {p}. "
            f"Скачанное цело в {tmp} — закрой другие копии приложения и перезапусти.")
    os.replace(tmp, p)                      # атомарная замена готовым каталогом
    return p
```

- [ ] **Step 3: Синтакс-проверка и пометить файл разрешённым**

```bash
.venv/Scripts/python.exe -c "import ast; ast.parse(open('model_store.py', encoding='utf-8').read())"
git add model_store.py
```

Коммит будет один на весь мердж — в Task 4 (git не умеет коммитить мердж частями).

### Task 2: Разрешение dictate.py

**Files:**
- Modify: `dictate.py` (разрешение конфликта)

**Interfaces:**
- Consumes: `model_store.ensure_downloaded(mid, kind=..., on_progress=...)` из Task 1; `backends.select_backend`, `backends.cpu_fallback_backend`, `backends.OpenVINOBackend` (уже в main).
- Produces: `DictationApp` со STATES `(..., "error")`, атрибутом `_last_error`, методами `load_model()` (error-state + OV-фолбэк) и `_download_and_load()`. GUI (Task 3) опирается на `_last_error` и состояние `"error"`.

Логика совмещения: от ветки — STATES с `"error"`, `_last_error`, безопасный `parse_hotkey`, защита `start_rec`, None-safe `language_probability`, `start()` c `try/except return`; от main — разбиение на `load_model`/`_download_and_load`, OV-фолбэк на CPU, `kind=self.backend.model_kind`. Комбинация: ошибки ловятся ВОКРУГ фолбэка (фолбэк — внутренняя попытка №2, и только если и она упала — состояние `error`).

- [ ] **Step 1: Записать целевые load_model/_download_and_load**

Секции `__init__`, `_print_state`, `start_rec`, `transcribe`, `start` — взять СТОРОНУ ВЕТКИ без изменений (конфликтные маркеры: выбрать вариант из `theirs`). Метод `load_model` — совмещённый, записать так:

```python
    # ── загрузка модели ──────────────────────────────────────
    def load_model(self):
        """Грузит модель. Сбой OpenVINO в auto-режиме -> тихий откат на CPU
        (спека Фазы 2). При окончательном сбое (нет сети, OOM, битая модель,
        device='cuda' без GPU) НЕ виснет в loading: обнуляет backend, переводит
        UI в 'error' с текстом причины и пробрасывает исключение наверх."""
        import backends
        try:
            self.backend = backends.select_backend(self.cfg)
            try:
                self._download_and_load()
            except Exception as e:
                if not (self.cfg.device == "auto"
                        and isinstance(self.backend, backends.OpenVINOBackend)):
                    raise
                print(f"[fallback] OpenVINO не поднялся ({e}); перехожу на CPU",
                      file=sys.stderr, flush=True)
                self.backend = backends.cpu_fallback_backend(self.cfg)
                self._download_and_load()
            self._last_error = None
        except Exception as e:
            self.backend = None
            self._last_error = str(e)
            print(f"[load_model] не смог загрузить модель: {e}", file=sys.stderr)
            self._set_state("error")
            raise

    def _download_and_load(self):
        import model_store
        mid = self.backend.model_id
        if mid and not model_store.is_cached(mid):
            self._set_state("downloading")
            model_store.ensure_downloaded(
                mid, kind=self.backend.model_kind,
                on_progress=lambda m: print(
                    f"Скачиваю модель '{m}' (первый запуск, может занять минуты)…",
                    flush=True))
        self._set_state("loading")
        t0 = time.perf_counter()
        self.backend.load()
        print(f"Модель '{mid or self.backend.name}' на {self.backend.device_label} "
              f"за {time.perf_counter() - t0:.1f} c.", flush=True)
        self._set_state("idle")
```

Внимание: `self._set_state("idle")` в конце `_download_and_load` (как в main), а `self._last_error = None` — после успешной попытки в `load_model`.

- [ ] **Step 2: Проверить отсутствие конфликтных маркеров и синтаксис**

```bash
grep -n "<<<<<<<\|>>>>>>>\|=======" dictate.py; echo "exit=$? (1 = маркеров нет)"
.venv/Scripts/python.exe -c "import ast; ast.parse(open('dictate.py', encoding='utf-8').read())"
git add dictate.py
```

### Task 3: Разрешение gui.py

**Files:**
- Modify: `gui.py` (разрешение конфликта)

**Interfaces:**
- Consumes: `DictationApp._last_error`, состояние `"error"` (Task 2); `gui_theme.resolve_theme/set_active_theme/build_palette/STATE_RGB/STATE_TEXT` (придут из ветки автоматически).
- Produces: рабочий `MainWindow` с темами, error-состоянием и откатом настроек. Ничего нового наружу.

Карта совмещения по зонам конфликта (обе стороны сохраняются, если не сказано иное):

| Зона | Решение |
|---|---|
| Импорты, `_check_icon_url`, `_row`, `TitleBar` | сторона ВЕТКИ |
| Карты `MODELS`/`COMPUTES`/`DEVICES` | сторона MAIN (turbo, auto, igpu/npu) |
| `THEMES` | сторона ВЕТКИ (добавить рядом с картами) |
| `_safe_engine_call` | ВЗЯТЬ от main, но заменить `bridge.stateChanged.emit(f"ошибка: ...")` на запись ошибки в engine + emit `"error"` (код ниже) |
| `_build_settings_page` (тема-комбо, словарь-`QPlainTextEdit`→`hotwords`, автозапуск) | сторона ВЕТКИ |
| `apply_theme`, `_theme_changed`, `_autostart_toggled` | сторона ВЕТКИ |
| `set_state` | сторона ВЕТКИ (busy-логика + error→hint) |
| `_apply_settings` / reload | СОВМЕСТИТЬ: код `_reload_with_rollback` ниже |
| `make_icon`, `_run_selftest` | сторона ВЕТКИ |
| `main()` (Fusion, single-instance, tray_refresh, colorSchemeChanged) | сторона ВЕТКИ + от main обёртка `_safe_engine_call(engine.start, ...)` |

- [ ] **Step 1: Записать совмещённые _safe_engine_call и _reload_with_rollback**

```python
def _safe_engine_call(fn, engine, bridge):
    """Зов метода движка в фоновом потоке: ошибка -> состояние 'error' в UI,
    а не молчаливая смерть потока (иначе окно вечно висит на «Скачиваю…»)."""
    try:
        fn()
    except Exception as e:
        print(f"[engine] {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        if engine is not None and getattr(engine, "_last_error", None) is None:
            engine._last_error = str(e)
        if bridge is not None:
            bridge.stateChanged.emit("error")
```

Внутри `_apply_settings` (ветка перезагрузки модели) и новый метод:

```python
        if self.engine and (c.model, c.device, c.compute_type) != old:
            import threading
            self.set_state("loading")
            threading.Thread(target=lambda: self._reload_with_rollback(old),
                             daemon=True).start()

    def _reload_with_rollback(self, old):
        """reload_model в фоне; при ошибке — откатить model/device/compute_type
        в config.json и поднять прежний рабочий бэкенд. Иначе нерабочий выбор
        (нет такого устройства / модель не поднялась) застревает в конфиге,
        и каждый следующий запуск приложения падает так же."""
        import config as _cfg
        emit = self.bridge.stateChanged.emit if self.bridge else self.set_state
        try:
            if not self.engine.reload_model():   # False = движок занят записью
                emit("idle")                     # не виснуть в loading
        except Exception as e:
            print(f"[engine] {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            c = self.cfg
            c.model, c.device, c.compute_type = old
            _cfg.save(c)
            self.engine._last_error = f"{str(e)[:100]} — настройки откачены"
            emit("error")
            _safe_engine_call(self.engine.reload_model, self.engine, self.bridge)
```

В `main()`: `threading.Thread(target=lambda: _safe_engine_call(engine.start, engine, bridge), daemon=True).start()`.

Примечание для исполнителя: в ветке `reload_model` возвращает bool «не занят» — проверить фактическую сигнатуру в слитом `dictate.py` (`grep -n "def reload_model" dictate.py`); если метода/возврата bool нет — взять его из ветки: `git show origin/feature/desktop-reliability-ui-installer:dictate.py` и перенести.

- [ ] **Step 2: Пройти файл от начала до конца, убрать все маркеры конфликтов**

```bash
grep -n "<<<<<<<\|>>>>>>>\|=======" gui.py; echo "exit=$? (1 = маркеров нет)"
.venv/Scripts/python.exe -c "import ast; ast.parse(open('gui.py', encoding='utf-8').read())"
git add gui.py
```

### Task 4: Тесты мерджа, merge-коммит, PR

**Files:**
- Test: все `test_*.py`, `smoke_gui.py`

- [ ] **Step 1: Прогнать полный тестовый набор**

```bash
.venv/Scripts/python.exe -m pytest test_postprocess.py test_backends.py test_paths.py test_transcribe_pipeline.py test_robustness.py test_theme.py -v
```

Expected: PASS все. `test_frozen_smoke.py` пропустится/упадёт без собранного exe — запускать так: `.venv/Scripts/python.exe -m pytest test_frozen_smoke.py -v`; если он требует dist — пометить skip-условием уже должно быть в файле (проверить; если нет — допустимо отложить до Фазы E, зафиксировав в выводе задачи).

- [ ] **Step 2: Смоук GUI офскрин**

```bash
.venv/Scripts/python.exe smoke_gui.py
```

Expected: exit 0, без traceback.

- [ ] **Step 3: Завершить мердж и запушить**

```bash
git commit --no-edit   # merge-коммит с авто-сообщением
git push -u origin merge/phase1-desktop
gh pr create --title "merge: phase 1 (themes, reliability, installer) into main with phase 2 (OpenVINO)" --body "Совмещение июньской ветки Фазы 1 с влитой Фазой 2. Конфликты разрешены в model_store.py (atomic download + OV marker), dictate.py (error-state + OV-фолбэк), gui.py (темы + rollback настроек).

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 4: Ручная проверка Руслана на ноутбуке (гейт)**

Запустить `.venv\Scripts\python.exe gui.py`, проверить: переключение темы Система/Светлая/Тёмная на лету; галочки в настройках рисуются галочками; диктовка на iGPU работает; длинная диктовка (30+ секунд) — латиница внутри русских слов не появляется. После одобрения: `gh pr merge --merge`, `git checkout main`, `git pull`.

---

## Фаза B: структура репозитория + переименование в Reku

### Task 5: Пакетная структура reku/ + tests/ + scripts/ + packaging/

**Files:**
- Create: `reku/__init__.py`, `reku/__main__.py`
- Move (git mv): `gui.py, gui_theme.py, gui_widgets.py, dictate.py, backends.py, postprocess.py, config.py, model_store.py, cuda_setup.py, autostart.py → reku/`; `test_*.py, smoke_gui.py, selftest_pipeline.py → tests/`; `diag.py, diag_halluc.py, diag_paste.py, bench_backends.py, ab_test.py, render_preview.py, make_ico.py → scripts/`; `whisper_ptt.spec → packaging/reku.spec`, `whisper_ptt.iss → packaging/reku.iss`, `build.ps1 → packaging/build.ps1`
- Modify: все перемещённые файлы (импорты), `.gitignore`

**Interfaces:**
- Produces: пакет `reku` — все внутренние импорты вида `from reku import config`; запуск `pythonw -m reku`; тесты импортируют `from reku import postprocess` и т.д. Task 6–15 работают в этой раскладке.

- [ ] **Step 1: Переместить файлы**

```bash
mkdir -p reku tests scripts packaging
git mv gui.py gui_theme.py gui_widgets.py dictate.py backends.py postprocess.py config.py model_store.py cuda_setup.py autostart.py reku/
git mv test_backends.py test_paths.py test_postprocess.py test_robustness.py test_theme.py test_transcribe_pipeline.py test_frozen_smoke.py smoke_gui.py selftest_pipeline.py tests/
git mv diag.py diag_halluc.py diag_paste.py bench_backends.py ab_test.py render_preview.py make_ico.py scripts/
git mv whisper_ptt.spec packaging/reku.spec
git mv whisper_ptt.iss packaging/reku.iss
git mv build.ps1 packaging/build.ps1
rm -rf __pycache__
```

(Список `tests/` сверить с фактическим составом после мерджа: `ls test_* smoke_gui.py selftest_pipeline.py`.)

- [ ] **Step 2: Создать точку входа пакета**

`reku/__init__.py`:

```python
"""Reku — локальная диктовка на Windows: голос → текст в активное окно по push-to-talk."""
APP_NAME = "Reku"
```

`reku/__main__.py`:

```python
"""Запуск: python -m reku (или pythonw -m reku без консоли)."""
from reku.gui import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Переписать импорты во всех перемещённых файлах**

Правило: внутри пакета `reku/` плоские `import config` / `import backends` / `import model_store` / `import postprocess` / `import cuda_setup` / `import gui_theme as T` / `from gui_widgets import ...` / `from dictate import ...` / `import autostart` → `from reku import config` (и аналогично) либо `from reku import gui_theme as T`, `from reku.gui_widgets import ...`, `from reku.dictate import ...`. То же в `tests/` и `scripts/`. Найти все места:

```bash
grep -rn "^import \(config\|backends\|model_store\|postprocess\|cuda_setup\|autostart\|gui_theme\|dictate\)\|^from \(config\|backends\|model_store\|postprocess\|cuda_setup\|autostart\|gui_theme\|gui_widgets\|dictate\|gui\) import\|import gui_theme\|import cuda_setup" reku/ tests/ scripts/
```

ВАЖНО: ленивые импорты внутри функций (`import backends` в `dictate.load_model`, `import cuda_setup` в `backends.CTranslate2Backend.load` и т.п.) тоже переписать (`from reku import backends`). Порядок «cuda_setup до faster_whisper» сохраняется автоматически — это внутренняя строка тех же функций.

- [ ] **Step 4: Поправить пути в packaging/**

`packaging/reku.spec`: точка входа `['../reku/__main__.py']` (или `os.path.join(ROOT, 'reku', '__main__.py')` с `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPECPATH)))` — сверить с фактической структурой spec из ветки), `name='Reku'` пока НЕ трогать (Task 7). `packaging/build.ps1`: `$root = Split-Path $PSScriptRoot` (корень репо), пути к spec/ico/dist от корня; вызов `make_ico.py` → `scripts/make_ico.py`. `packaging/reku.iss`: `Source: "..\dist\whisper_ptt\*"` — путь через `..` (имя каталога dist сменится в Task 7).

- [ ] **Step 5: Прогнать тесты из новой раскладки**

```bash
.venv/Scripts/python.exe -m pytest tests/ -v
.venv/Scripts/python.exe tests/smoke_gui.py
.venv/Scripts/python.exe -c "import reku; from reku import gui, dictate, backends, config, model_store; print('imports ok')"
```

Expected: PASS/ok. Типовые падения: незамеченный плоский импорт — искать grep'ом из Step 3.

- [ ] **Step 6: Коммит**

```bash
git add -A
git commit -m "refactor: package layout — reku/ package, tests/, scripts/, packaging/"
```

### Task 6: data_dir → %APPDATA%\Reku + мягкая миграция (TDD)

**Files:**
- Modify: `reku/config.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: `reku.APP_NAME` (Task 5).
- Produces: `config.data_dir()` возвращает `%APPDATA%\Reku` во frozen; `config.migrate_data_dir()` — переименование старого каталога; зовётся из `data_dir()` лениво.

- [ ] **Step 1: Написать падающий тест миграции**

Добавить в `tests/test_paths.py` (существующие тесты data_dir сохранить, поправив ожидаемое имя на `Reku`):

```python
def test_data_dir_migrates_old_whisper_ptt(tmp_path, monkeypatch):
    """Старый %APPDATA%/whisper_ptt переименовывается в %APPDATA%/Reku (модели не перекачиваются)."""
    from reku import config
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    old = tmp_path / "whisper_ptt"; old.mkdir()
    (old / "config.json").write_text("{}", encoding="utf-8")
    d = config.data_dir()
    assert d == str(tmp_path / "Reku")
    assert (tmp_path / "Reku" / "config.json").is_file()
    assert not old.exists()


def test_data_dir_no_migration_when_new_exists(tmp_path, monkeypatch):
    """Если новый каталог уже есть — старый не трогаем (не перезатираем данные)."""
    from reku import config
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    (tmp_path / "whisper_ptt").mkdir()
    (tmp_path / "Reku").mkdir()
    assert config.data_dir() == str(tmp_path / "Reku")
    assert (tmp_path / "whisper_ptt").exists()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

```bash
.venv/Scripts/python.exe -m pytest tests/test_paths.py -v
```

Expected: FAIL (data_dir возвращает whisper_ptt-путь / нет миграции).

- [ ] **Step 3: Реализовать в reku/config.py**

В `data_dir()` заменить имя каталога на `Reku` и добавить миграцию (точную текущую реализацию `data_dir` посмотреть в файле; каркас):

```python
_OLD_DIR_NAME = "whisper_ptt"   # имя до переименования продукта (июль 2026)


def _migrate_data_dir(new: str) -> None:
    """Переименовать старый каталог данных в новый (модели ~3 ГБ не перекачиваются).
    Каталог занят/ошибка -> работаем дальше, попробуем при следующем старте."""
    old = os.path.join(os.path.dirname(new), _OLD_DIR_NAME)
    if os.path.isdir(old) and not os.path.exists(new):
        try:
            os.replace(old, new)
            print(f"[config] каталог данных перенесён: {old} -> {new}")
        except OSError as e:
            print(f"[config] не смог перенести {old} -> {new}: {e}", file=sys.stderr)


def data_dir() -> str:
    if getattr(sys, "frozen", False):
        d = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Reku")
        _migrate_data_dir(d)
        return d
    return os.path.dirname(os.path.abspath(__file__ if "__file__" in globals() else "."))
```

ВНИМАНИЕ: не-frozen ветка `data_dir` сейчас возвращает каталог скрипта — после переезда в пакет это `reku/`; для dev-запуска конфиг должен остаться в КОРНЕ репо (как раньше): вернуть `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` (родитель пакета). Проверить существующим тестом test_paths (он сравнивает с каталогом config.json — обновить ожидание на корень репо).

- [ ] **Step 4: Тесты зелёные + коммит**

```bash
.venv/Scripts/python.exe -m pytest tests/test_paths.py -v
git add reku/config.py tests/test_paths.py
git commit -m "feat: data_dir %APPDATA%/Reku with soft migration from whisper_ptt"
```

### Task 7: Продуктовые имена Reku во всех поверхностях

**Files:**
- Modify: `reku/gui.py`, `packaging/reku.spec`, `packaging/reku.iss`, `packaging/build.ps1`, `tests/test_frozen_smoke.py`, `README.md` (только шапка; полная переписка — Task 14)

**Interfaces:**
- Consumes: `reku.APP_NAME`.
- Produces: единая константа имени; env-переменная селфтеста `REKU_SELFTEST`.

- [ ] **Step 1: gui.py — все видимые строки**

`from reku import APP_NAME` и заменить: заголовок окна/`TitleLabel` «whisper_ptt» → `APP_NAME`; тултип трея `f"whisper_ptt — ..."` → `f"{APP_NAME} — ..."`; имя single-instance сокета `"whisper_ptt-single"`-подобное (найти фактическое: `grep -n "QLocalServer\|listen(" reku/gui.py`) → `"reku-single-instance"`; `WHISPER_PTT_SELFTEST` → `REKU_SELFTEST` (и в комментариях селфтеста «whisper_ptt/selftest.json» — путь берётся из data_dir, поправится сам).

- [ ] **Step 2: packaging — spec/iss/build.ps1**

`reku.spec`: `name='Reku'` (onedir → `dist/Reku/Reku.exe`). `reku.iss`: `#define MyAppName "Reku"`, `MyAppExe "Reku.exe"`, НОВЫЙ AppId-GUID (сгенерить: `python -c "import uuid; print(uuid.uuid4())"`), `Source: "..\dist\Reku\*"`. `build.ps1`: пути `dist\Reku\Reku.exe`, сообщение и имя ярлыка `Reku.lnk`.

- [ ] **Step 3: tests/test_frozen_smoke.py — env и пути**

`WHISPER_PTT_SELFTEST` → `REKU_SELFTEST`, путь exe `dist/Reku/Reku.exe` (посмотреть фактические строки в файле и заменить все вхождения старого имени).

- [ ] **Step 4: Проверка + коммит**

```bash
grep -rn "whisper_ptt" reku/ packaging/ tests/ scripts/ --include="*.py" --include="*.spec" --include="*.iss" --include="*.ps1" | grep -v "_OLD_DIR_NAME\|до переименования"
```

Expected: пусто (остаются только строки миграции в config.py). Прогнать `pytest tests/ -v` + `tests/smoke_gui.py` → PASS.

```bash
git add -A && git commit -m "feat: rename product to Reku (window, tray, spec, installer, selftest env)"
```

### Task 8: Переименование репозитория GitHub

- [ ] **Step 1: Rename + проверка remote**

```bash
gh repo rename reku --yes
git remote -v    # gh сам обновляет origin на .../Small-coder-AI/reku.git
git push origin main 2>&1 | head -3   # смоук: связь жива
```

Старый URL `whisper_ptt` продолжит перенаправлять. Локальную папку `d:\Dev\Whisper_PTT\whisper_ptt` не трогаем (по желанию Руслана переименует руками позже).

---

## Фаза C: установка одной командой

### Task 9: install.ps1 — детект железа, Python, код, venv

**Files:**
- Create: `install.ps1` (корень репо)

**Interfaces:**
- Produces: `install.ps1 [-SourcePath <локальная-папка>] [-Uninstall]`. Установка в `%LOCALAPPDATA%\Programs\Reku`; профили `cuda`/`intel`/`cpu`.

- [ ] **Step 1: Записать install.ps1 (первая часть: детект, python, код, venv)**

```powershell
# install.ps1 — установка Reku одной командой.
#   irm https://raw.githubusercontent.com/Small-coder-AI/reku/main/install.ps1 | iex
# Локальная отладка:  .\install.ps1 -SourcePath D:\Dev\Whisper_PTT\whisper_ptt
# Удаление:           .\install.ps1 -Uninstall
param(
    [string]$SourcePath = "",
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
$AppName    = "Reku"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
$RepoZip    = "https://github.com/Small-coder-AI/reku/archive/refs/heads/main.zip"
$StartMenu  = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$RunKey     = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# (обработка -Uninstall добавляется в Task 10 — блок Invoke-Uninstall сразу после констант)

# ── 1. Железо ────────────────────────────────────────────────
Write-Step "Определяю железо..."
$gpus = (Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue).Name -join "; "
$profile = "cpu"
if ($gpus -match "NVIDIA") { $profile = "cuda" }
elseif ($gpus -match "Intel.*(Arc|Iris|Graphics)") { $profile = "intel" }
Write-Host "    Видеоадаптеры: $gpus"
Write-Host "    Профиль установки: $profile"

# ── 2. Python 3.12 ───────────────────────────────────────────
Write-Step "Ищу Python 3.12..."
$py = $null
foreach ($cand in @("py -3.12", "python")) {
    try {
        $v = & $cand.Split()[0] $cand.Split()[1..99] --version 2>$null
        if ($v -match "Python 3\.12\.") { $py = $cand; break }
    } catch {}
}
if (-not $py) {
    Write-Step "Python 3.12 не найден — ставлю через winget (тихо)..."
    winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget не смог поставить Python. Поставь Python 3.12 с python.org и запусти скрипт снова." }
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $py = "py -3.12"
}
Write-Host "    Python: $(& $py.Split()[0] $py.Split()[1..99] --version)"

# ── 3. Код ───────────────────────────────────────────────────
Write-Step "Получаю код в $InstallDir..."
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$codeItems = @("reku", "scripts", "packaging", "requirements.txt", "requirements.lock.txt")
if ($SourcePath) {
    foreach ($it in $codeItems) { Copy-Item -Recurse -Force (Join-Path $SourcePath $it) $InstallDir }
} else {
    $tmp = Join-Path $env:TEMP "reku_dl"; Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    Invoke-WebRequest $RepoZip -OutFile "$tmp.zip"
    Expand-Archive "$tmp.zip" $tmp -Force
    $src = Get-ChildItem $tmp -Directory | Select-Object -First 1   # reku-main/
    foreach ($it in $codeItems) { Copy-Item -Recurse -Force (Join-Path $src.FullName $it) $InstallDir }
    Remove-Item -Recurse -Force $tmp, "$tmp.zip" -ErrorAction SilentlyContinue
}

# ── 4. Окружение ─────────────────────────────────────────────
$venv = Join-Path $InstallDir ".venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    Write-Step "Создаю виртуальное окружение..."
    & $py.Split()[0] $py.Split()[1..99] -m venv $venv
}
$vpy = Join-Path $venv "Scripts\python.exe"
Write-Step "Ставлю зависимости (профиль $profile; это займёт несколько минут)..."
$req = Get-Content (Join-Path $InstallDir "requirements.txt")
if ($profile -ne "cuda") { $req = $req | Where-Object { $_ -notmatch "^nvidia-" } }
if ($profile -eq "cpu")  { $req = $req | Where-Object { $_ -notmatch "^openvino" } }
$reqFile = Join-Path $InstallDir "requirements.effective.txt"
$req | Set-Content $reqFile -Encoding UTF8
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r $reqFile
if ($LASTEXITCODE -ne 0) { throw "pip не смог поставить зависимости (см. вывод выше)." }
```

(Ярлыки/автозапуск/финал — Task 10, дописываются в этот же файл.)

- [ ] **Step 2: Синтакс-проверка**

```powershell
powershell -NoProfile -Command "[void][ScriptBlock]::Create((Get-Content -Raw install.ps1)); 'parse ok'"
```

Expected: `parse ok`.

- [ ] **Step 3: Коммит**

```bash
git add install.ps1 && git commit -m "feat: install.ps1 — hardware detect, python bootstrap, venv, profile deps"
```

### Task 10: install.ps1 — ярлыки, автозапуск, -Uninstall, идемпотентность

**Files:**
- Modify: `install.ps1`

- [ ] **Step 1: Дописать ярлыки/автозапуск/финал (в конец основного потока)**

```powershell
# ── 5. Ярлыки ────────────────────────────────────────────────
Write-Step "Создаю ярлыки..."
$pyw = Join-Path $venv "Scripts\pythonw.exe"
$ico = Join-Path $InstallDir "packaging\app.ico"
function New-Shortcut($path) {
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($path)
    $sc.TargetPath = $pyw; $sc.Arguments = "-m reku"
    $sc.WorkingDirectory = $InstallDir
    if (Test-Path $ico) { $sc.IconLocation = $ico }
    $sc.Save()
}
New-Shortcut (Join-Path $StartMenu "$AppName.lnk")
$desk = Read-Host "Ярлык на рабочий стол? [Y/n]"
if ($desk -ne "n") { New-Shortcut (Join-Path ([Environment]::GetFolderPath("Desktop")) "$AppName.lnk") }

# ── 6. Автозапуск ────────────────────────────────────────────
$auto = Read-Host "Запускать $AppName при старте Windows? [y/N]"
if ($auto -eq "y") {
    Set-ItemProperty -Path $RunKey -Name $AppName -Value "`"$pyw`" -m reku"
    Write-Host "    Автозапуск включён (можно выключить в настройках $AppName)."
}

Write-Host ""
Write-Host "Готово! Запускай $AppName из меню Пуск." -ForegroundColor Green
Write-Host "Модель распознавания скачается при первом запуске (1.5–3 ГБ, вопрос терпения)."
```

И блок удаления (функция + вызов в начале, ЗАМЕНИВ временную строку из Task 9 на прямой вызов):

```powershell
function Invoke-Uninstall {
    Write-Step "Удаляю $AppName..."
    Remove-Item (Join-Path $StartMenu "$AppName.lnk") -ErrorAction SilentlyContinue
    Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "$AppName.lnk") -ErrorAction SilentlyContinue
    Remove-ItemProperty -Path $RunKey -Name $AppName -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue
    $data = Join-Path $env:APPDATA $AppName
    if (Test-Path $data) {
        $ans = Read-Host "Удалить данные и скачанные модели ($data)? [y/N]"
        if ($ans -eq "y") { Remove-Item -Recurse -Force $data }
    }
    Write-Host "Удалено." -ForegroundColor Green
}
if ($Uninstall) { Invoke-Uninstall; return }
```

Разместить `function Invoke-Uninstall` и `if ($Uninstall) {...}` СРАЗУ после блока `param()`/констант, до шага детекта железа.

- [ ] **Step 2: Проверить parse + идемпотентность логики**

```powershell
powershell -NoProfile -Command "[void][ScriptBlock]::Create((Get-Content -Raw install.ps1)); 'parse ok'"
```

Пройти глазами: повторный запуск не пересоздаёт venv (проверка `Test-Path`), код заменяется поверх (Copy-Item -Force), pip докачивает новое. Ярлыки перезаписываются молча (Save поверх).

- [ ] **Step 3: Коммит**

```bash
git add install.ps1 && git commit -m "feat: install.ps1 — shortcuts, autostart, uninstall, idempotent update"
```

### Task 11: app.ico в репо + ручная проверка установки на ноутбуке (гейт)

**Files:**
- Create: `packaging/app.ico` (сгенерировать и закоммитить)
- Modify: `.gitignore` (если app.ico игнорируется)

- [ ] **Step 1: Сгенерировать и закоммитить иконку**

```bash
.venv/Scripts/python.exe scripts/make_ico.py   # проверить, куда пишет; целевой путь packaging/app.ico
grep -n "app.ico" .gitignore && sed -i '/app\.ico/d' .gitignore
git add packaging/app.ico .gitignore
git commit -m "chore: commit packaging/app.ico (used by installer shortcuts)"
```

(Если `make_ico.py` пишет в другой путь — поправить в нём выходной путь на `packaging/app.ico` тем же коммитом.)

- [ ] **Step 2: Чистая установка на ноутбуке (руками, с Русланом)**

```powershell
# из PowerShell (не из bash):
cd D:\Dev\Whisper_PTT\whisper_ptt
.\install.ps1 -SourcePath D:\Dev\Whisper_PTT\whisper_ptt
```

Проверить: профиль определился `intel`; установка завершилась зелёным; ярлык в Пуске запускает окно; диктовка работает (модель уже в %APPDATA% после миграции — качаться не должна); повторный запуск скрипта проходит без ошибок. Dev-клон остаётся рабочей копией для разработки — установка живёт отдельно в `%LOCALAPPDATA%\Programs\Reku`.

---

## Фаза D: доводка UI

### Task 12: Строка «Работает: устройство · модель» в настройках

**Files:**
- Modify: `reku/gui.py`
- Test: `tests/smoke_gui.py` (дополнение)

**Interfaces:**
- Consumes: `engine.backend.device_label`, `engine.backend.model_name` (есть у CT2/OV бэкендов).

- [ ] **Step 1: Добавить label в _build_settings_page (после секции СИСТЕМА)**

```python
        self.runtime_lbl = QLabel("Работает: —")
        self.runtime_lbl.setObjectName("HintLabel")
        lay.addWidget(self.runtime_lbl)
```

И метод + вызов в `set_state` при `state == "idle"` (рядом с `_update_hint()`):

```python
    def _update_runtime_label(self):
        b = getattr(self.engine, "backend", None) if self.engine else None
        if b is None:
            self.runtime_lbl.setText("Работает: —")
            return
        mdl = getattr(b, "model_name", None) or b.name
        self.runtime_lbl.setText(f"Работает: {b.device_label} · {mdl}")
```

- [ ] **Step 2: Смоук + ручной запуск + коммит**

В `tests/smoke_gui.py` добавить проверку (по образцу существующих): окно строится, `win.runtime_lbl.text().startswith("Работает:")`. Запустить:

```bash
.venv/Scripts/python.exe tests/smoke_gui.py && .venv/Scripts/python.exe -m pytest tests/ -v
git add reku/gui.py tests/smoke_gui.py && git commit -m "feat(gui): show active device and model in settings"
```

### Task 13: Оценка палитры с Русланом (гейт)

- [ ] **Step 1: Отрендерить обе темы в PNG и показать**

```bash
.venv/Scripts/python.exe scripts/render_preview.py   # проверить аргументы скрипта; получить PNG тёмной и светлой
```

Показать Руслану оба PNG (SendUserFile). Вопрос: тёмная всё ещё «слишком чёрная»?

- [ ] **Step 2: При необходимости — поднять фон**

Если да: в `reku/gui_theme.py` в тёмной палитре поднять фоновые константы на 1–2 тона (например `#0F1115 → #14171D`, карточки пропорционально), перегенерить превью, показать снова. Итерации до «ок». Коммит: `git commit -m "feat(theme): lighten dark background per feedback"`.

---

## Фаза E: предпубликационная уборка

### Task 14: README + LICENSE + .gitignore

**Files:**
- Modify: `README.md`, `.gitignore`
- Create: `LICENSE`

- [ ] **Step 1: LICENSE (MIT)**

```text
MIT License

Copyright (c) 2026 Ruslan Kobernik

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: README.md — переписать под Reku**

Структура (содержимое адаптировать из текущего README, он точен по фактам):

```markdown
# Reku

Локальная диктовка для Windows: зажми клавишу — скажи — текст появится у курсора.
Полностью офлайн: звук не покидает компьютер. Русский и английский (и ещё 90+ языков Whisper).
Два движка под одним капотом: NVIDIA CUDA (faster-whisper) и Intel iGPU/NPU (OpenVINO) —
программа сама выбирает лучшее для твоего железа, на слабом железе сама берёт модель полегче.

## Установка

Открой PowerShell и выполни:

    irm https://raw.githubusercontent.com/Small-coder-AI/reku/main/install.ps1 | iex

Скрипт сам определит железо, поставит только нужное (~1–3 ГБ) и сделает ярлыки.
Модель распознавания скачается при первом запуске. Обновление — та же команда.
Удаление: скачать install.ps1 и запустить с ключом -Uninstall.

## Использование
[хоткей по умолчанию правый Ctrl, режимы ptt/toggle, трей — сжать из текущего README]

## Настройки — config.json
[таблица из текущего README, обновив: language="ru" по умолчанию, поля theme и hotwords]

## Разработка
    git clone https://github.com/Small-coder-AI/reku && cd reku
    python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
    .venv\Scripts\python -m reku        # запуск
    .venv\Scripts\python -m pytest tests/ -v
Сборка exe (запасной путь): packaging\build.ps1 [-Installer]

## Как это работает / Почему cuda_setup / Intel OpenVINO
[перенести технические разделы текущего README без изменений, поправив пути на reku/]
```

- [ ] **Step 3: .gitignore + чистка артефактов**

Проверить/добавить: `dist/`, `build/`, `installer/`, `requirements.effective.txt`, `*.log`, `_preview_*.png`. Удалить из рабочей копии `bench_run.log` (в git его нет). Убедиться, что `packaging/app.ico` НЕ игнорируется.

- [ ] **Step 4: Тесты + коммит**

```bash
.venv/Scripts/python.exe -m pytest tests/ -v
git add README.md LICENSE .gitignore && git rm --cached bench_run.log 2>/dev/null; rm -f bench_run.log
git commit -m "docs: README for Reku with one-line install; add MIT LICENSE"
```

### Task 15: Контрольная сборка exe на ноутбуке

- [ ] **Step 1: Собрать**

```powershell
# PowerShell:
cd D:\Dev\Whisper_PTT\whisper_ptt
.\packaging\build.ps1
```

Expected: `dist\Reku\Reku.exe` существует. (Сборка на ноуте = intel-профиль venv; CUDA-DLL в неё не попадут — это ок, exe-путь останется запасным и для RTX-ПК собирается на нём же.)

- [ ] **Step 2: Смоук собранного exe**

```powershell
$env:REKU_SELFTEST = "1"; .\dist\Reku\Reku.exe; $LASTEXITCODE
```

Expected: exit 0 (`transcribe_ok: true` в `%APPDATA%\Reku\selftest.json`; поле device = cpu или igpu). Затем обычный запуск двойным кликом — окно открывается, трей живёт.

- [ ] **Step 3: Финальный прогон всего + коммит остатков + PR фаз B–E**

```bash
.venv/Scripts/python.exe -m pytest tests/ -v && .venv/Scripts/python.exe tests/smoke_gui.py
git push -u origin HEAD
gh pr create --title "refactor: Reku — package layout, rename, one-line install, docs" --body "Фазы B–E финишного рефакторинга по спеке 2026-07-05.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

После ревью и мерджа — доложить Руслану: готово к публикации по его команде (сама публикация вне плана).
