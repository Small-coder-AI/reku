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
