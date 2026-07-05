# Reku

Локальная диктовка на Windows: голос → текст в активное окно по push-to-talk.
Полностью офлайн. Два движка под одним контрактом: faster-whisper/CTranslate2
(NVIDIA CUDA или CPU) и OpenVINO GenAI (Intel iGPU/NPU). Самая тяжёлая модель
(`large-v3`) работает быстро на обоих: ~0.7 с на короткую фразу (RTX 3050,
float16) и ~1–2 с на фразы 10–24 с (Intel Arc 140T, int8).

## Запуск

```powershell
# десктопный UI (основной) — окно + трей
.\.venv\Scripts\pythonw.exe gui.py      # без консоли
.\.venv\Scripts\python.exe  gui.py      # с консолью (логи/латентность)

# только консоль, без окна
.\.venv\Scripts\python.exe dictate.py
```

Окно: тёмное безрамочное, mic-orb (статус цветом), живой вэйвформ при записи,
карточка с распознанным текстом, кнопка записи, выбор языка, шестерёнка → настройки
(модель/устройство/точность/хоткей/режим/VAD/фильтр). Закрытие окна → сворачивание
в трей; выход — из меню трея.

Дождись `Готово…` (модель грузится ~6 с) — затем зажми хоткей (по умолчанию правый
Ctrl), скажи фразу, отпусти. Текст вставится по курсору. **Держи запущенным один
инстанс** (gui.py *или* dictate.py) — каждый грузит свою копию модели в 8 ГБ VRAM.

## Сборка .exe (переносимый, в автозапуск)

```powershell
.\build.ps1 -Clean              # PyInstaller --onedir --windowed -> dist\whisper_ptt\
.\build.ps1 -Clean -Installer   # + setup.exe (Inno Setup) -> installer\whisper_ptt-setup.exe
.\.venv\Scripts\python.exe test_frozen_smoke.py   # проверка: GPU реально работает в сборке
```

Результат — `dist\whisper_ptt\whisper_ptt.exe` (двойной клик, иконка в трее). Модель
(~3 ГБ) **не вшита** — качается при первом запуске в `%APPDATA%\whisper_ptt\models\`.

**Инсталлятор** (`whisper_ptt.iss`, Inno Setup, per-user — без админ-прав): `whisper_ptt-setup.exe`
ставит в `%LOCALAPPDATA%\Programs\whisper_ptt`, делает ярлык в Пуске (+ опц. рабочий стол),
опц. автозапуск (на установленный exe) и деинсталлятор. Нужен Inno Setup:
`winget install JRSoftware.InnoSetup`.
Главный риск сборки — CUDA-DLL: `cuda_setup.py` во frozen добавляет `_internal\nvidia\*\bin`
в PATH до импорта faster-whisper; `test_frozen_smoke.py` проверяет, что `device=cuda`
(а не тихий CPU-фолбэк). **Автозапуск** — чекбокс «Запускать при старте Windows» в
настройках (пишет в `HKCU\…\Run` путь к `.exe`). Файлы сборки: `whisper_ptt.spec`,
`build.ps1`, `make_ico.py`, `autostart.py`, `test_frozen_smoke.py`.

## Настройка — `config.json`

Создаётся при первом запуске. Ключевое:

| параметр | по умолчанию | смысл |
|---|---|---|
| `model` / `compute_type` | `large-v3` / `auto` | какую модель грузить; `large-v3-turbo` — почти то же качество, в разы быстрее |
| `device` | `auto` | `auto` → CUDA → Intel GPU (OpenVINO) → CPU; явно: `cuda`/`igpu`/`npu`/`cpu` |
| `hotkey` | `ctrl_r` | имя клавиши pynput (`ctrl_r`, `f9`, …) или один символ |
| `mode` | `ptt` | `ptt` — зажим; `toggle` — нажал/нажал |
| `theme` | `system` | `system` (за темой Windows) / `dark` / `light` |
| `language` | `"ru"` | `"ru"` фиксирует язык (меньше латиницы внутри слов); `""` — авто |
| `initial_prompt` | русский якорь | смещает декодер к кириллице; держи русским, термины — в `hotwords` |
| `hotwords` | словарь терминов | бренды/термины через запятую (GitHub, OData, 1С…) — точечный биас |
| `beam_size` | `5` | `1` быстрее, `5` точнее |
| `vad_filter` | `true` | режет тишину/шум — **главная** защита от галлюцинаций |
| `condition_on_previous_text` | `false` | `false` = меньше петель-повторов |
| `no_repeat_ngram_size` | `3` | запрет повтора n-грамм при декоде |
| `drop_hallucinations` | `true` | резать многословные титры-фантомы Whisper (блок-лист в postprocess.py) |
| `min_language_probability` | `0.0` | `>0` (напр. 0.4) — глушить вывод, если язык распознан неуверенно (вероятно не речь) |
| `insert_method` | `paste` | `paste` (буфер+Ctrl+V) или `type` (посимвольно) |

**Латиница внутри русских слов** лечится связкой `language="ru"` + русский `initial_prompt`
+ термины в `hotwords` (см. `ab_test.py` — сравнивает конфиги на одном дубле голоса и
печатает «% смешанных слов»). **Тема** переключается в настройках на лету; `system`
следует Windows. Если модель не загрузилась (нет сети/устройства) — окно показывает
**«Ошибка»** с причиной, а не виснет в «Загрузке».

Трей-меню тоже переключает `mode` и `language` на лету (пишет в config.json).

## Файлы

- `gui.py` — **десктопный UI на PySide6** (окно + трей). Основная точка входа.
- `gui_theme.py` — палитра + QSS. `gui_widgets.py` — MicOrb + WaveformStrip.
- `dictate.py` — ядро `DictationApp` (запись→распознавание→вставка) + консольный запуск.
- `config.py` / `config.json` — настройки.
- `postprocess.py` — фильтр галлюцинаций (чистые функции).
- `cuda_setup.py` — кладёт nvidia-DLL в PATH (см. ниже). **Импортируется первым.**
- `requirements.txt` (верхнеуровневые пины) / `requirements.lock.txt` (полный freeze).
- `diag.py`, `diag_halluc.py` — диагностика GPU и галлюцинаций.
- `test_postprocess.py`, `selftest_pipeline.py`, `smoke_gui.py` — тесты.
- `render_preview.py` — офскрин-рендер UI в PNG (для доводки вида).

## Почему `cuda_setup.py` (важная заметка про GPU)

CTranslate2 на Windows грузит `cublas64_12.dll` / `cudnn*.dll` через голый
`LoadLibrary`, который ищет их только рядом с `ctranslate2.dll`, в System32 и в
**PATH**. pip-пакеты `nvidia-*` кладут DLL в `site-packages/nvidia/<lib>/bin`,
которого в PATH нет. `os.add_dll_directory()` ct2 **не видит** (тот флаг чтит ctypes,
не ct2). Поэтому `cuda_setup.py` добавляет эти каталоги в `PATH` до импорта
faster_whisper. Без этого `encode()` падает: `cublas64_12.dll cannot be loaded`
(это похоже на «работает на CPU», но на деле — краш в фоновом потоке).
`nvidia-cuda-runtime-cu12` не нужен — ct2 линкует cudart статически.

## Intel iGPU/NPU (OpenVINO) — заметка

На машинах без NVIDIA `auto` выбирает Intel-графику через OpenVINO GenAI:
готовые int8-модели качаются с HF (`OpenVINO/whisper-*-int8-ov`, карта —
`OV_MODEL_MAP` в backends.py), первая загрузка компилирует модель под
конкретный GPU (десятки секунд, разово), дальше — кэш в `ov_cache/` и старт
~2–3 с. VAD работает (Silero из faster-whisper), фильтры галлюцинаций
работают; `min_language_probability` в этом пути НЕ действует (движок не
сообщает уверенность в языке), decode — greedy (beam_size игнорируется).
Скорость проверена на Arc 140T; на слабых iGPU (UHD 6xx и т.п.) large-v3
может компилироваться/работать долго — тогда выбери `large-v3-turbo` или
`small` в настройках. Если OpenVINO в auto-режиме не поднялся вовсе
(драйвер/память) — приложение само откатывается на CPU + small.
На машинах без NVIDIA пакеты `nvidia-*` можно не ставить
(`grep -v '^nvidia-' requirements.txt`). Бенч скорости на своих фразах:
`python bench_backends.py record`, затем `run` (отчёт в
`bench_audio/bench_results.md`).

## Что проверено и что нет

Проверено headless (без участия пользователя):
- GPU-инференс честный (0.69 с на 4 с аудио), venv самодостаточен;
- пайплайн `transcribe`→фильтр (тишина/шум → пусто), пороги, дедуп, блок-лист;
- сборка трея (иконки, меню) без ошибок.

Требует ручной проверки (нужен реальный keypress/окно/GUI-сессия):
- вставка текста по курсору в реальном приложении;
- режим `toggle` и смена хоткея;
- появление иконки в трее, клики меню, смена цвета по статусу.
