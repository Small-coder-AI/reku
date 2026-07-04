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

    @property
    def model_kind(self) -> str:
        """Вид модели для model_store.ensure_downloaded: 'ct2' | 'ov'."""
        return "ct2"

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
