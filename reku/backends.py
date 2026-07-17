"""Абстракция бэкенда инференса + авто-детект железа.

Три локальных движка: CTranslate2/faster-whisper (NVIDIA CUDA и CPU),
OpenVINO GenAI (Intel iGPU/NPU) и whisper.cpp+Vulkan (AMD; подпроцесс
whisper-server, механика в whisper_cpp.py). ApiBackend (OpenRouter/OpenAI/…) —
заглушка. Все бэкенды возвращают из transcribe() одинаковый (segments, info),
поэтому UI и постпроцессинг не зависят от источника.

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

# Готовые ggml-модели whisper.cpp на HF (репо ggerganov/whisper.cpp; имена файлов
# проверены по HF API 2026-07-17). Имя модели из конфига -> одиночный файл.
# Квант q5: large-v3 ~1.1 ГБ — влезает в 8 ГБ VRAM (RX 6600 XT тестера) с запасом;
# для tiny/base/small на HF лежит q5_1, а не q5_0 — это не опечатка.
WCPP_MODEL_MAP = {
    "large-v3": "ggml-large-v3-q5_0.bin",
    "large-v3-turbo": "ggml-large-v3-turbo-q5_0.bin",
    "turbo": "ggml-large-v3-turbo-q5_0.bin",
    "large-v2": "ggml-large-v2-q5_0.bin",
    "medium": "ggml-medium-q5_0.bin",
    "small": "ggml-small-q5_1.bin",
    "base": "ggml-base-q5_1.bin",
    "tiny": "ggml-tiny-q5_1.bin",
}

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


def _compression_ratio(text: str) -> float:
    """Как в faster-whisper: длина текста / длина его zlib-сжатия.
    Зацикленный повтор жмётся сильно -> ratio высокий (порог фильтра 2.4)."""
    import zlib
    data = text.encode("utf-8")
    return len(data) / len(zlib.compress(data)) if data else 0.0


def chunks_to_segments(chunks):
    """result.chunks (WhisperPipeline) -> сегменты контракта faster-whisper.
    Наш postprocess читает .text и .compression_ratio; OV его не отдаёт,
    поэтому считаем сами — иначе фильтр «пересжатых» сегментов мёртв."""
    from types import SimpleNamespace
    return [SimpleNamespace(text=c.text, start=c.start_ts, end=c.end_ts,
                            compression_ratio=_compression_ratio(c.text))
            for c in (chunks or [])]


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


# Подстановка модели в АВТО-режиме на iGPU — результат ворот бенча
# (docs/superpowers/specs/2026-07-04-phase2-openvino-igpu-design.md, «Порядок работ»).
# Пустая карта: large-v3 на Arc 140T уложилась в критерий с запасом
# (warm 1.2–2.0 с на фразах 11–24 с, bench_results.md 2026-07-04) — не понижаем.
IGPU_AUTO_SUBSTITUTE = {}


def _cuda_available() -> bool:
    """Есть ли пригодный CUDA-GPU для CTranslate2. Любой сбой = нет GPU."""
    try:
        from reku import cuda_setup  # noqa: F401 — кладёт nvidia-DLL в PATH
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _ov_gpu_available() -> bool:
    """Есть ли Intel GPU для OpenVINO. Любой сбой (нет пакета/драйвера) = нет."""
    try:
        import openvino
        return "GPU" in openvino.Core().available_devices
    except Exception:
        return False


def _amd_gpu_available() -> bool:
    """Есть ли AMD-GPU (Radeon) + Vulkan-рантайм для whisper.cpp. Любой сбой = нет.
    Детект по активным видеоадаптерам (EnumDisplayDevicesW — мгновенно, без
    подпроцессов); vulkan-1.dll кладёт в System32 драйвер GPU — без неё
    whisper-server не запустится."""
    import os
    if os.name != "nt":
        return False
    try:
        vk = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                          "System32", "vulkan-1.dll")
        if not os.path.isfile(vk):
            return False
        from reku import whisper_cpp
        names = " ".join(whisper_cpp.display_adapter_names()).lower()
        return "amd" in names or "radeon" in names
    except Exception:
        return False


def resolve_runtime(device, compute_type, model, *, cuda_available,
                    ov_gpu_available=False, amd_available=False):
    """Чистая функция: ('auto'|'cuda'|'cpu'|'igpu'|'npu'|'amd', compute, model) ->
    конкретные значения. Авто-цепочка: cuda -> amd -> igpu -> cpu. AMD раньше
    igpu сознательно: дискретный Radeon сильно быстрее десктопных Intel-iGPU
    (частая связка Intel-CPU + Radeon-dGPU), а обратная связка Arc-dGPU +
    Radeon-iGPU практически не встречается. Понижение модели — ТОЛЬКО в auto:
    на cpu тяжёлые -> small, на igpu — по карте ворот бенча; на amd не понижаем
    (large-v3-q5_0 ~1.1 ГБ влезает в типичные 8 ГБ VRAM). compute_type на amd
    не действует — квантизация зашита в файл модели."""
    auto = (device == "auto")
    if auto:
        dev = ("cuda" if cuda_available else
               "amd" if amd_available else
               "igpu" if ov_gpu_available else "cpu")
    else:
        dev = device

    comp = compute_type
    if comp in ("", "auto", None):
        comp = "float16" if dev == "cuda" else "int8"

    mdl = model
    if auto and dev == "cpu" and model in HEAVY_MODELS:
        mdl = CPU_FALLBACK_MODEL
    if auto and dev == "igpu":
        mdl = IGPU_AUTO_SUBSTITUTE.get(model, model)

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
        from reku import cuda_setup  # noqa: F401 — строго до faster_whisper
        from faster_whisper import WhisperModel
        from reku import model_store
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
            # пусто -> None: пустую строку get_prompt тоже игнорирует, но None чище
            hotwords=(getattr(cfg, "hotwords", "") or None),
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
        from reku import model_store
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


class WhisperCppBackend(Backend):
    """AMD-GPU (и любой другой Vulkan-GPU) через whisper.cpp: наш CI-билд
    whisper-server крутится подпроцессом на 127.0.0.1 и держит модель в VRAM
    между диктовками; модели — одиночные ggml-файлы с HF (WCPP_MODEL_MAP).
    Вся механика (движок/процесс/HTTP) — в whisper_cpp.py.

    Ограничено by design (не «чинить» симметрию с CUDA-путём):
      - hotwords и no_repeat_ngram_size движок не принимает (аналогов нет);
      - condition_on_previous_text НЕ настраивается: сервер v1.9.1 всегда
        работает в режиме no_context=true (наш дефолт False и есть);
      - language_probability считается ТОЛЬКО при включённом фильтре
        min_language_probability: это доп. проход детекции языка (лишняя
        латентность на каждую фразу), без фильтра он не нужен.
    """
    name = "whispercpp"

    def __init__(self, model):
        self.model_name = model
        self._server = None
        self._vk_devices = None

    @property
    def device_label(self) -> str:
        # 0 найденных Vulkan-устройств = ggml тихо считает на CPU — показываем
        # честно, а не маскируем под GPU (урок CUDA-пути с DLL)
        if self._vk_devices == 0:
            return "CPU (Vulkan не найден)"
        return "GPU (Vulkan)"

    @property
    def model_id(self):
        return WCPP_MODEL_MAP.get(self.model_name)

    @property
    def model_kind(self) -> str:
        return "ggml"

    def load(self):
        import os
        import sys
        from reku import whisper_cpp, model_store, config
        rid = self.model_id
        if rid is None:
            raise ValueError(
                f"модель {self.model_name!r} недоступна для whisper.cpp (AMD); "
                f"выбери одну из: {', '.join(sorted(set(WCPP_MODEL_MAP)))}")
        exe = whisper_cpp.ensure_engine(
            on_progress=lambda n: print(f"Скачиваю движок {n} (~45 МБ, один раз)…",
                                        flush=True))
        self._server = whisper_cpp.ServerProcess(
            exe, model_store.model_path(rid),
            log_path=os.path.join(config.data_dir(), "whisper-server.log"))
        self._server.start()
        self._vk_devices = self._server.vulkan_devices()
        if self._vk_devices == 0:
            print("[whispercpp] ggml не нашёл Vulkan-устройств — движок работает "
                  "на CPU (проверь драйвер видеокарты)", file=sys.stderr, flush=True)
        # Прогрев: самый первый инференс компилирует Vulkan-пайплайны — на свежем
        # драйверном кэше шейдеров это ДЕСЯТКИ секунд (замер на RTX 3050: 20 с,
        # дальше ~1 с). Платим здесь, в фазе loading, а не на первой диктовке.
        # beam_size как в дефолтном конфиге: greedy-прогрев не компилирует
        # пайплайны beam-декода, и первая фраза всё равно платила бы ~14 с.
        import numpy as np
        self._server.inference(
            whisper_cpp.encode_wav(np.zeros(1600, dtype=np.float32)),
            {"response_format": "json", "beam_size": 5})

    def transcribe(self, audio, cfg):
        from reku import whisper_cpp
        duration = len(audio) / 16000.0
        want_prob = bool(cfg.min_language_probability)
        if cfg.vad_filter:
            audio = apply_vad(audio)
            if audio is None:
                return [], whisper_cpp.make_wcpp_info(cfg.language, duration)
        fields = {
            "response_format": "verbose_json",
            "language": cfg.language or "auto",
            "beam_size": cfg.beam_size,
            # подавление не-речевых токенов (♪ и т.п.) — ближе к дефолту
            # faster-whisper (suppress_tokens=-1), меньше мусора на шуме
            "suppress_nst": "true",
        }
        if cfg.initial_prompt:
            fields["prompt"] = cfg.initial_prompt
        if not want_prob:
            # детекция языка — лишний проход энкодера, нужна только фильтру
            fields["no_language_probabilities"] = "true"
        resp = self._inference(whisper_cpp.encode_wav(audio), fields)
        segments = whisper_cpp.segments_from_response(resp)
        prob = resp.get("detected_language_probability") if want_prob else None
        lang = (resp.get("detected_language") or cfg.language) if want_prob else cfg.language
        return segments, whisper_cpp.make_wcpp_info(lang, duration, prob)

    def _inference(self, wav: bytes, fields: dict) -> dict:
        """Запрос с автоперезапуском сервера. whisper-server — отдельный процесс
        и может умереть сам по себе (сброс/обновление драйвера GPU во время
        Vulkan-вычислений, антивирус, OOM). Без рестарта каждая следующая
        диктовка молча падала бы до перезапуска всего приложения."""
        import sys
        import urllib.error
        if self._server is None:
            raise RuntimeError("модель ещё не загружена (whisper-server не запущен)")
        if not self._server.alive():
            print("[whispercpp] whisper-server умер — перезапускаю",
                  file=sys.stderr, flush=True)
            self._server.stop()
            self._server.start()
        try:
            return self._server.inference(wav, fields)
        except urllib.error.URLError:
            # умер/завис между проверкой и запросом — одна повторная попытка
            print("[whispercpp] whisper-server не ответил — перезапускаю",
                  file=sys.stderr, flush=True)
            self._server.stop()
            self._server.start()
            return self._server.inference(wav, fields)

    def close(self):
        s, self._server = self._server, None
        if s is not None:
            s.stop()

    def __del__(self):
        # reload_model просто бросает старый бэкенд — сервер должен умереть с ним;
        # исключения глотаем: __del__ на shutdown интерпретатора кидать не должен
        try:
            self.close()
        except Exception:
            pass


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


def cpu_fallback_backend(cfg):
    """Запасной CPU-бэкенд, когда OpenVINO в auto-режиме не поднялся
    (слабый/незнакомый iGPU, драйвер, нехватка памяти — спека Фазы 2,
    «Обработка ошибок»). Тяжёлые модели понижаются до small, как в auto+cpu."""
    mdl = CPU_FALLBACK_MODEL if cfg.model in HEAVY_MODELS else cfg.model
    return CTranslate2Backend(model=mdl, device="cpu", compute_type="int8")


def select_backend(cfg, *, cuda_probe=None, ov_probe=None, amd_probe=None):
    """Маршрутизация: cfg.device -> конкретный Backend (ещё не загружен).
    Пробы зовутся только в auto-режиме и лениво: amd — только если CUDA нет,
    ov — только если нет ни CUDA, ни AMD (порядок цепочки см. resolve_runtime)."""
    if cfg.device == "api":
        return ApiBackend(cfg)
    cuda = (cuda_probe or _cuda_available)() if cfg.device == "auto" else False
    amd = ((amd_probe or _amd_gpu_available)()
           if (cfg.device == "auto" and not cuda) else False)
    ov = ((ov_probe or _ov_gpu_available)()
          if (cfg.device == "auto" and not cuda and not amd) else False)
    dev, comp, mdl = resolve_runtime(cfg.device, cfg.compute_type, cfg.model,
                                     cuda_available=cuda, ov_gpu_available=ov,
                                     amd_available=amd)
    if dev == "amd":
        return WhisperCppBackend(model=mdl)
    if dev in ("igpu", "npu"):
        return OpenVINOBackend(model=mdl, device=dev)
    return CTranslate2Backend(model=mdl, device=dev, compute_type=comp)
