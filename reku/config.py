"""Конфиг Reku. Хранится в config.json в каталоге данных приложения (см. data_dir()).

Цель — лёгкий интерфейс, в который подгружаются модели: всё, что можно
переключить (модель, точность, хоткей, режим, язык, фильтры), живёт здесь.
При первом запуске config.json создаётся со значениями по умолчанию.
"""
import os
import sys
import json
from dataclasses import dataclass, asdict, fields

from reku import APP_NAME   # безопасно: reku/__init__.py ничего не импортирует (цикла нет)

_OLD_DIR_NAME = "whisper_ptt"   # имя каталога данных до переименования продукта (июль 2026)

_RESOLVED_DATA_DIR = None   # кэш результата data_dir() на весь процесс (см. её docstring)


def _migrate_data_dir(new: str) -> str:
    """Переименовать старый каталог данных (whisper_ptt) в новый (Reku), чтобы модели
    (~3 ГБ) не перекачивались заново после переименования продукта. Возвращает
    РАБОЧИЙ каталог: new — когда переносить нечего, новый уже есть или перенос
    удался; old — когда переименование не удалось (каталог занят и т.п.): тогда
    продолжаем работать со старым, а перенос попробуется при следующем запуске.
    Возврат нового пути при ошибке был бы капканом: приложение тут же создало бы
    пустой новый каталог (makedirs в save()/model_store), ворота миграции
    `not os.path.exists(new)` закрылись бы навсегда — модели осиротели бы."""
    old = os.path.join(os.path.dirname(new), _OLD_DIR_NAME)
    if os.path.isdir(old) and not os.path.exists(new):
        try:
            os.replace(old, new)
            print(f"[config] каталог данных перенесён: {old} -> {new}")
        except OSError as e:
            print(f"[config] не смог перенести {old} -> {new}: {e}; "
                  f"работаю со старым каталогом", file=sys.stderr)
            return old
    return new


def data_dir() -> str:
    """Каталог данных приложения.
    Frozen (.exe): %APPDATA%\\<APP_NAME> — из Program Files писать нельзя; при первом
    обращении после обновления со старого имени мягко переносит каталог целиком
    (см. _migrate_data_dir) — единственный побочный эффект этой функции; если
    перенос не удался, возвращается СТАРЫЙ каталог (данные не сиротеют, попытка
    повторится при следующем запуске).
    Из исходников: корень репозитория (родитель пакета reku/) — там же лежат
    config.json и models/ для разработки, как и до переезда config.py в reku/.

    Результат кэшируется на уровне модуля (_RESOLVED_DATA_DIR) и считается ОДИН
    РАЗ за жизнь процесса. Без этого случай, когда первый вызов вернул СТАРЫЙ
    каталог (перенос не удался — занят и т.п.), а к следующему вызову препятствие
    исчезло бы, на середине работы переключил рабочий каталог на новый — а
    CONFIG_PATH (вычислен один раз при импорте, из первого же вызова data_dir())
    продолжал бы смотреть на старый; настройки, сохранённые после переключения,
    писались бы не туда и терялись. Кэш фиксирует каталог на весь процесс."""
    global _RESOLVED_DATA_DIR
    if _RESOLVED_DATA_DIR is not None:
        return _RESOLVED_DATA_DIR
    if getattr(sys, "frozen", False):
        new = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
        _RESOLVED_DATA_DIR = _migrate_data_dir(new)
    else:
        _RESOLVED_DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return _RESOLVED_DATA_DIR


CONFIG_PATH = os.path.join(data_dir(), "config.json")


@dataclass
class Config:
    # ── модель ───────────────────────────────────────────────
    model: str = "large-v3"          # large-v3 / medium / small / ... или путь
    device: str = "auto"             # auto / cuda / cpu / igpu / npu / api
    compute_type: str = "auto"       # auto / float16 / int8_float16 / int8 / float32

    # ── API-бэкенд (зарезервировано, реализация в Фазе 2) ────
    api_provider: str = "openrouter"
    api_base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = ""
    api_model: str = ""

    # ── ввод ─────────────────────────────────────────────────
    hotkey: str = "ctrl_r"           # имя клавиши pynput (Key.<name>) или один символ
    mode: str = "ptt"                # "ptt" = зажим, "toggle" = вкл/выкл по нажатию
    sample_rate: int = 16000

    # ── интерфейс ────────────────────────────────────────────
    theme: str = "system"            # system (за темой Windows) / dark / light

    # ── распознавание ────────────────────────────────────────
    language: str = "ru"             # "" = авто-детект; "ru" фиксирует язык (меньше латиницы)
    beam_size: int = 5               # 1 = быстрее, 5 = точнее
    # initial_prompt — РУССКИЙ якорь: смещает декодер к кириллице и лечит латиницу
    # внутри русских слов (латинский промпт раньше тянул латинские сабворды). Сами
    # термины держим отдельно в hotwords — точечный биас без стилевого «утекания».
    initial_prompt: str = "Это диктовка на русском языке."
    hotwords: str = ("Claude Code, GitHub, Docker, 1С, "
                     "faster-whisper, Postgres, OData.")   # словарь терминов (sot_prev-биас)
    vad_filter: bool = True          # режет тишину/шум до распознавания (главная защита)
    condition_on_previous_text: bool = False  # False = меньше петель-повторов
    no_repeat_ngram_size: int = 3    # запрет повтора n-грамм при декоде (0 = выкл)

    # ── пост-фильтр галлюцинаций ─────────────────────────────
    drop_hallucinations: bool = True         # резать фирменные фантомы Whisper
    max_compression_ratio: float = 2.4       # выше — текст «переспрессован» (повторы)
    min_language_probability: float = 0.0    # 0 = выкл; не-речь даёт ~0.2

    # ── вставка ──────────────────────────────────────────────
    insert_method: str = "paste"     # "paste" (буфер+Ctrl+V) | "type" (посимвольно)
    restore_clipboard: bool = False  # ВЫКЛ: восстановление буфера ломает асинхронную
                                     # вставку (гонка) — как в простой рабочей версии
    trailing_space: bool = False     # добавлять пробел после вставленного текста

    @property
    def lang_or_none(self):
        return self.language or None


# старый латинский дефолт initial_prompt (до фикса латиницы) — мигрируем на лету
_LEGACY_INITIAL_PROMPT = ("Claude Code, GitHub, Docker, 1С, "
                          "faster-whisper, Postgres, OData.")


def _migrate(cfg: Config) -> bool:
    """Чинит конфиги старых установок. Возвращает True, если что-то поменялось.
    Латиница-внутри-слов: старый латинский initial_prompt -> русский якорь, а бренды
    переезжают в hotwords (точечный биас). Трогаем ТОЛЬКО нетронутый старый дефолт —
    свой кастомный промпт пользователя не перезаписываем."""
    if cfg.initial_prompt.strip() == _LEGACY_INITIAL_PROMPT:
        cfg.initial_prompt = Config.initial_prompt        # новый русский якорь
        if not cfg.hotwords.strip():
            cfg.hotwords = _LEGACY_INITIAL_PROMPT          # бренды -> hotwords
        return True
    return False


def load(path: str = CONFIG_PATH) -> Config:
    """Грузит конфиг; недостающие поля берёт из дефолтов; создаёт файл, если нет."""
    cfg = Config()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            known = {f.name for f in fields(Config)}
            for k, v in data.items():
                if k in known:
                    setattr(cfg, k, v)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[config] не смог прочитать {path}: {e}; беру дефолты")
        if _migrate(cfg):
            save(cfg, path)
            print(f"[config] миграция: латинский промпт -> русский якорь + hotwords")
    else:
        save(cfg, path)
        print(f"[config] создан {path}")
    return cfg


def save(cfg: Config, path: str = CONFIG_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, ensure_ascii=False, indent=2)
