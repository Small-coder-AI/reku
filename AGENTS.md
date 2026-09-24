# AGENTS.md

Shared repository instructions for Claude Code and Codex.

## Что это

Reku — локальная push-to-talk диктовка для Windows (PySide6: окно + трей). Три движка
распознавания: faster-whisper/CTranslate2 (NVIDIA CUDA), OpenVINO GenAI (Intel iGPU/NPU)
и whisper.cpp+Vulkan (AMD; подпроцесс whisper-server), автовыбор по железу
(auto-цепочка cuda → amd → igpu → cpu) с фолбэком на CPU.
Репозиторий публичный: github.com/Small-coder-AI/reku.

План работ по фазам с чек-листами — `docs/ROADMAP.md`: перед задачей сверяйся с ним,
сделанное отмечай там же.

Дистрибуция: основной путь — `install.ps1` (ставит код последнего релиза — `-Ref main`
или `-Ref vX.Y.Z` для другого; Python + venv в `%LOCALAPPDATA%\Programs\Reku`; обновление =
повторный запуск, код заменяется целиком, данные живут отдельно). Правки в `main` доходят
до пользователей install.ps1 только с новым релизом (тегом). Запасные пути: frozen exe (PyInstaller + Inno Setup) — его же
собирает CI на пуш тега `vX.Y.Z` и кладёт в GitHub Release (`.github/workflows/release.yml`);
и `uv tool install "reku[cuda|intel] @ git+…"` (extras по железу в pyproject.toml).
Версия живёт в ДВУХ местах — `pyproject.toml` и `reku/__init__.py` (CI сверяет обе с тегом);
пины зависимостей — в ТРЁХ: `requirements.txt` + `requirements.lock.txt` (install.ps1 ставит
первый с constraints из второго), `pyproject.toml` (прямые + `[tool.uv] constraint-dependencies`
для транзитивных) и `uv.lock` (перегенерировать `uv lock`) — менять синхронно.
Qt — `PySide6-Essentials` (не полный `PySide6`: Addons не используются).

## Команды

PowerShell, из корня репозитория; dev-окружение — `.venv`.

```powershell
.venv\Scripts\python -m reku          # GUI с консолью (логи, латентность)
.venv\Scripts\pythonw -m reku         # GUI без консоли
.venv\Scripts\python tests\test_paths.py    # один тест
Get-ChildItem tests\test_*.py -Exclude test_frozen_smoke.py | ForEach-Object { .venv\Scripts\python $_.FullName }   # все тесты
.\packaging\build.ps1                 # сборка exe -> dist\Reku\Reku.exe
.\packaging\build.ps1 -Installer      # + инсталлятор (нужен Inno Setup)
```

- Тесты — самостоятельные скрипты (печатают OK/FAIL, завершаются `SystemExit`), **не pytest**.
  Не конвертировать в pytest и не запускать pytest'ом — module-level `SystemExit` ломает collection.
- CI (`.github/workflows/ci.yml`, windows-latest) на каждый push/PR гоняет все тесты
  (кроме frozen smoke) с `QT_QPA_PLATFORM=offscreen` и `ruff check .` (правила F и E9).
- `tests\test_frozen_smoke.py` — смоук СОБРАННОГО exe: требует готовый `dist\Reku\Reku.exe`
  и `REKU_SMOKE_DEVICE=cuda|igpu` под реальное железо машины. В общий прогон не входит.
- Рендер превью UI без GUI-сессии: `scripts/render_preview.py` с `QT_QPA_PLATFORM=offscreen`,
  `QT_QPA_FONTDIR=C:\Windows\Fonts` (иначе вместо текста квадратики) и `PREVIEW_THEME=dark|light`.

## Архитектура

Поток: `gui.py` (окно/трей, точка входа `-m reku`) → `dictate.py` `DictationApp`
(запись sounddevice → транскрипция → вставка текста) → `backends.py` (выбор и обёртки
движков) → `postprocess.py` (фильтр галлюцинаций, чистые функции).

Критические неочевидные связи (то, что легко сломать «уборкой»):

- **`cuda_setup.py` импортируется первым**, строго до faster_whisper: CTranslate2 грузит
  cublas/cudnn через голый `LoadLibrary` (ищет только в PATH), `os.add_dll_directory()`
  он не видит. Без этого CUDA-путь падает в фоновом потоке, маскируясь под «работает на CPU».
- **`config.data_dir()` — единственный источник правды путей** (config.json, models/):
  frozen exe и установка install.ps1 (`%LOCALAPPDATA%\Programs\Reku`, хоть и из исходников!)
  → `%APPDATA%\Reku`; обычный dev-чекаут → корень репозитория. Результат кэшируется на весь
  процесс — см. docstring, там объяснено почему. Упоминания `whisper_ptt` в `config.py` и
  `tests/test_paths.py` — **намеренная миграция** каталога данных со старого имени продукта,
  не мусор для чистки.
- **OpenVINO-путь**: `hotwords` передаются (WhisperGenerationConfig их принимает). Декод
  по умолчанию greedy: CT2-поле `beam_size` здесь намеренно НЕ используется (молча замедлило
  бы iGPU), beam search — только через опт-ин `ov_num_beams`. `min_language_probability`
  не действует — движок не отдаёт уверенность в языке.
- **AMD-путь (whisper.cpp)**: `hotwords` эмулируются через `prompt` (отдельного поля у
  сервера нет); `no_repeat_ngram_size` и `condition_on_previous_text` не действуют (сервер
  v1.9.1 всегда no_context). Запросы к локальному серверу — через `_LOCAL_OPENER` мимо прокси
  (у пользователей бывает системный прокси); не заменять на голый `urlopen`.
  Движок — НАШ CI-билд whisper-server (workflow `build-whisper-cpp.yml` → служебный релиз
  `engine-whisper-cpp-*-vulkan`); пин версии и sha256 — константы в `reku/whisper_cpp.py`,
  при обновлении движка менять тег/имя/sha256 разом. Первый инференс на машине компилирует
  Vulkan-шейдеры (десятки секунд) — поэтому в `load()` есть прогрев, не удалять.
- **Колбэки хоткея (`_on_press`/`_on_release`) работают в потоке низкоуровневого хука
  клавиатуры**: в них только постановка команды в очередь (`request_start/stop/load`),
  всю работу делает рабочий поток `DictationApp`. Никакого I/O, PortAudio и долгих локов в
  колбэках: превышение `LowLevelHooksTimeout` — и Windows молча снимает хук. GUI зовёт те
  же `request_*`. Слушатель клавиш стартует независимо от загрузки модели.
- **`REKU_SELFTEST=1`** — хук в `gui.main()`: вместо UI выполняется короткая самопроверка,
  результат в `%APPDATA%\Reku\selftest.json` (на этом построен test_frozen_smoke.py).
- GUI при старте снимает залипшие offline-флаги HuggingFace (`TRANSFORMERS_OFFLINE` и т.п.),
  иначе скачивание моделей ломается у пользователей с такими флагами в реестре — не удалять.

## Конвенции

- Комментарии, docstrings, user-facing строки — на русском; идентификаторы и сообщения
  коммитов — на английском.
- README двуязычный: `README.md` (EN, основной) и `README.ru.md` — правки документации
  вносить в **оба**.
- `.ps1` и `.iss` с кириллицей сохранять в **UTF-8 with BOM** — без BOM PowerShell и ISCC
  ломают кодировку.
- Репозиторий публичный — **никаких личных данных**: имён (кроме автора в LICENSE и
  метаданных пакета), путей профилей, железа и софта конкретных машин, личных словарей.
  Это касается кода, комментариев, дефолтов конфига, документации, заметок и сообщений
  коммитов; в примерах — вымышленные значения.
- `docs-archive/` — локальный архив внутренних планов, `memory/` — локальная память агентов;
  оба в git не идут (gitignored).
