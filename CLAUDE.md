# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Что это

Reku — локальная push-to-talk диктовка для Windows (PySide6: окно + трей). Два движка
распознавания: faster-whisper/CTranslate2 (NVIDIA CUDA) и OpenVINO GenAI (Intel iGPU/NPU),
автовыбор по железу с фолбэком на CPU. Репозиторий публичный: github.com/Small-coder-AI/reku.

Дистрибуция: основной путь — `install.ps1` (скачивает main.zip, ставит Python + venv в
`%LOCALAPPDATA%\Programs\Reku`; обновление = повторный запуск, код заменяется целиком,
данные живут отдельно). Запасной путь — frozen exe (PyInstaller + Inno Setup).

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
- **OpenVINO-путь ограничен by design**: greedy-декод (beam_size игнорируется), `hotwords`
  и `min_language_probability` не действуют — движок их не принимает. Не «чинить» симметрию
  с CUDA-путём.
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
- Дефолты конфига — нейтральные: не вшивать личные словари, пути и имена (репозиторий публичный).
- `docs-archive/` — локальный архив внутренних планов, в git не идёт (gitignored).
