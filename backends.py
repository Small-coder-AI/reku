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

# Готовые int8-модели OpenVINO на HF (проверено по HF API 2026-07-04).
# Имя модели из конфига -> репо для скачивания.
OV_MODEL_MAP = {
    "large-v3": "OpenVINO/whisper-large-v3-int8-ov",
    "large-v3-turbo": "OpenVINO/whisper-large-v3-turbo-int8-ov",
    "turbo": "OpenVINO/whisper-large-v3-turbo-int8-ov",
    "distil-large-v3": "OpenVINO/distil-whisper-large-v3-int8-ov",
    "large-v2": "OpenVINO/whisper-large-v2-int8-ov",
    "medium": "OpenVINO/whisper-medium-int8-ov",
    "small": "OpenVINO/whisper-small-int8-ov",
    "base": "OpenVINO/whisper-base-int8-ov",
    "tiny": "OpenVINO/whisper-tiny-int8-ov",
}


def ov_lang_token(language):
    """'ru' -> '<|ru|>' (формат WhisperPipeline); пустой язык -> None (авто)."""
    return f"<|{language}|>" if language else None


def chunks_to_segments(chunks):
    """result.chunks (WhisperPipeline) -> сегменты контракта faster-whisper.
    Наш postprocess читает .text и .compression_ratio (у OV её нет -> 0.0)."""
    from types import SimpleNamespace
    return [SimpleNamespace(text=c.text, start=c.start_ts, end=c.end_ts,
                            compression_ratio=0.0) for c in (chunks or [])]


def make_ov_info(language, duration):
    """info контракта faster-whisper. ВАЖНО: WhisperPipeline не сообщает
    уверенность в языке -> language_probability всегда 1.0, поэтому фильтр
    min_language_probability в OV-пути не действует (осознанная деградация)."""
    from types import SimpleNamespace
    return SimpleNamespace(language=language or "", language_probability=1.0,
                           duration=duration)


def apply_vad(audio, sample_rate=16000):
    """VAD-шаг для OV-пути: Silero из faster-whisper (он всё равно установлен
    для CPU/CUDA). None = речи нет; иначе склейка речевых кусков."""
    import numpy as np
    from faster_whisper.vad import get_speech_timestamps, collect_chunks
    chunks = get_speech_timestamps(audio, sampling_rate=sample_rate)
    if not chunks:
        return None
    pieces, _ = collect_chunks(audio, chunks, sampling_rate=sample_rate)
    return np.concatenate(pieces)


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
    """Intel iGPU/NPU через OpenVINO GenAI WhisperPipeline.

    Модели — готовые int8 с HF (OV_MODEL_MAP), без конвертации на машине.
    Вызовы generate() повторяют проверенные бенчем (bench_backends.py).
    """
    name = "openvino"

    def __init__(self, model, device):
        self.model_name = model
        self.device = device          # "igpu" | "npu"
        self._pipe = None

    @property
    def device_label(self) -> str:
        return ("Intel NPU (OpenVINO)" if self.device == "npu"
                else "Intel GPU (OpenVINO)")

    @property
    def model_id(self):
        return OV_MODEL_MAP.get(self.model_name)

    @property
    def model_kind(self) -> str:
        return "ov"

    def load(self):
        rid = self.model_id
        if rid is None:
            raise ValueError(
                f"модель {self.model_name!r} недоступна для Intel GPU/NPU; "
                f"выбери одну из: {', '.join(sorted(set(OV_MODEL_MAP)))}")
        import os
        import openvino_genai       # лениво: на машинах без OV не импортируется
        import model_store
        cache = os.path.join(model_store._data_dir(), "ov_cache")
        os.makedirs(cache, exist_ok=True)
        dev = "NPU" if self.device == "npu" else "GPU"
        props = {"CACHE_DIR": cache}
        if self.device == "npu":
            props["STATIC_PIPELINE"] = True   # требование WhisperPipeline на NPU
        self._pipe = openvino_genai.WhisperPipeline(
            model_store.model_path(rid), dev, **props)

    def transcribe(self, audio, cfg):
        duration = len(audio) / 16000.0
        if cfg.vad_filter:
            audio = apply_vad(audio)
            if audio is None:
                return [], make_ov_info(cfg.language, duration)
        kwargs = dict(task="transcribe", return_timestamps=True)
        lang = ov_lang_token(cfg.language)
        if lang:
            kwargs["language"] = lang
        if cfg.initial_prompt:
            kwargs["initial_prompt"] = cfg.initial_prompt
        # beam_size/no_repeat_ngram_size/condition_on_previous_text — CT2-специфика,
        # в GenAI не пробрасываются: greedy-декод (качество подтверждено бенчем).
        result = self._pipe.generate(audio.tolist(), **kwargs)
        segments = chunks_to_segments(getattr(result, "chunks", None))
        return segments, make_ov_info(cfg.language, duration)


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
