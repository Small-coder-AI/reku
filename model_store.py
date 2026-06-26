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


# Полный набор: модель грузится несколькими файлами. Проверяем не только model.bin,
# иначе ОБОРВАННАЯ докачка (есть model.bin, нет токенайзера) сочтётся «скачано» и
# WhisperModel упадёт при загрузке → UI зависнет в loading (см. dictate.load_model).
_REQUIRED = ("model.bin", "config.json")
_TOKENIZERS = ("tokenizer.json", "vocabulary.json", "vocabulary.txt")


def _dir_complete(d: str) -> bool:
    """В каталоге d лежит полный набор файлов модели (а не оборванная докачка):
    model.bin, config.json и хотя бы один файл токенайзера."""
    if not all(os.path.isfile(os.path.join(d, f)) for f in _REQUIRED):
        return False
    return any(os.path.isfile(os.path.join(d, t)) for t in _TOKENIZERS)


def is_cached(model: str) -> bool:
    """Скачана ли модель ПОЛНОСТЬЮ (а не оборванная докачка)."""
    return _dir_complete(model_path(model))


def ensure_downloaded(model: str, on_progress=None) -> str:
    """Гарантирует наличие модели локально. Возвращает путь к ней.
    on_progress(model) зовётся один раз перед началом скачивания (для UI).
    Качаем во временный каталог и атомарно переименовываем — прерванная докачка
    не оставит «полу-скачанный» каталог, который is_cached сочтёт готовым."""
    p = model_path(model)
    if is_cached(model):
        return p
    if on_progress:
        on_progress(model)
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
            f"Скачанное цело в {tmp} — закрой другие копии whisper_ptt и перезапусти.")
    os.replace(tmp, p)                      # атомарная замена готовым каталогом
    return p
