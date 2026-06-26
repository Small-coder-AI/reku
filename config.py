"""Конфиг whisper_ptt. Хранится в config.json рядом со скриптом.

Цель — лёгкий интерфейс, в который подгружаются модели: всё, что можно
переключить (модель, точность, хоткей, режим, язык, фильтры), живёт здесь.
При первом запуске config.json создаётся со значениями по умолчанию.
"""
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


@dataclass
class Config:
    # ── модель ───────────────────────────────────────────────
    model: str = "large-v3"          # large-v3 / medium / small / ... или путь
    device: str = "auto"             # auto / cuda / cpu / api
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
