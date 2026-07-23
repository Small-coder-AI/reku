"""Тесты бэкендов. Запуск (из корня репозитория): python tests/test_backends.py (GPU не нужен)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reku import backends
from reku.backends import resolve_runtime, select_backend, CTranslate2Backend, \
    OpenVINOBackend, ApiBackend
from types import SimpleNamespace as S


def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    return cond


ok = True

# resolve_runtime: auto + есть CUDA -> cuda/float16, модель не трогаем
ok &= check("auto+cuda -> cuda/float16/large-v3",
            resolve_runtime("auto", "auto", "large-v3", cuda_available=True)
            == ("cuda", "float16", "large-v3"))

# auto + нет CUDA + тяжёлая модель -> cpu/int8/small (понижение)
ok &= check("auto+no-cuda+heavy -> cpu/int8/small",
            resolve_runtime("auto", "auto", "large-v3", cuda_available=False)
            == ("cpu", "int8", "small"))

# auto + нет CUDA + лёгкая модель -> остаётся как есть
ok &= check("auto+no-cuda+light -> cpu/int8/base",
            resolve_runtime("auto", "auto", "base", cuda_available=False)
            == ("cpu", "int8", "base"))

# явный cpu НЕ понижает модель (это решение пользователя)
ok &= check("явный cpu не понижает модель",
            resolve_runtime("cpu", "auto", "large-v3", cuda_available=False)
            == ("cpu", "int8", "large-v3"))

# явный cuda + явный compute -> без изменений
ok &= check("явный cuda+float16",
            resolve_runtime("cuda", "float16", "medium", cuda_available=True)
            == ("cuda", "float16", "medium"))

# ── compute по возможностям карты (боевые случаи: GTX 1050 Ti, GTX 950) ──
# Pascal (CC 6.1, GTX 10xx): эффективного fp16 нет -> int8_float32, модель не трогаем
ok &= check("auto+cuda без fp16 -> int8_float32/large-v3",
            resolve_runtime("auto", "auto", "large-v3", cuda_available=True,
                            cuda_compute_types={"int8", "int8_float32", "float32"})
            == ("cuda", "int8_float32", "large-v3"))

# Maxwell (CC < 6.1, GTX 9xx): только fp32 -> float32, тяжёлая модель понижается
# (карты той эпохи с 2-4 ГБ VRAM, large в fp32 ~6 ГБ не влезает)
ok &= check("auto+cuda fp32-only -> float32/small",
            resolve_runtime("auto", "auto", "large-v3", cuda_available=True,
                            cuda_compute_types={"float32"})
            == ("cuda", "float32", "small"))

# fp32-only + лёгкая модель -> не трогаем
ok &= check("auto+cuda fp32-only+light -> float32/base",
            resolve_runtime("auto", "auto", "base", cuda_available=True,
                            cuda_compute_types={"float32"})
            == ("cuda", "float32", "base"))

# современная карта (RTX): float16 как раньше
ok &= check("auto+cuda с fp16 -> float16/large-v3",
            resolve_runtime("auto", "auto", "large-v3", cuda_available=True,
                            cuda_compute_types={"float16", "int8_float16",
                                                "int8", "int8_float32", "float32"})
            == ("cuda", "float16", "large-v3"))

# типы узнать не удалось (None) -> прежнее поведение, float16
ok &= check("cuda_compute_types=None -> float16 (совместимость)",
            resolve_runtime("auto", "auto", "large-v3", cuda_available=True,
                            cuda_compute_types=None)
            == ("cuda", "float16", "large-v3"))

# явный compute пользователя не подменяется, даже если карта его не умеет
# (ошибка ct2 всплывёт в UI — осознанный выбор должен падать громко)
ok &= check("явный float16 не подменяется",
            resolve_runtime("cuda", "float16", "medium", cuda_available=True,
                            cuda_compute_types={"float32"})
            == ("cuda", "float16", "medium"))

# явный cuda + compute=auto тоже адаптируется, но модель не понижается
# (понижение — только в auto-режиме устройства, как и на cpu-пути)
ok &= check("явный cuda+auto на fp32-only -> float32/large-v3",
            resolve_runtime("cuda", "auto", "large-v3", cuda_available=False,
                            cuda_compute_types={"float32"})
            == ("cuda", "float32", "large-v3"))

# select_backend: device=api -> ApiBackend (заглушка), .load() кидает NotImplementedError
cfg_api = S(device="api", compute_type="auto", model="small")
b = select_backend(cfg_api)
ok &= check("api -> ApiBackend", isinstance(b, ApiBackend))
try:
    b.load()
    ok &= check("ApiBackend.load кидает NotImplementedError", False)
except NotImplementedError:
    ok &= check("ApiBackend.load кидает NotImplementedError", True)

# select_backend: локальный путь -> CTranslate2Backend с разрешённым устройством
# (ov/amd-пробы тоже мокаются: на машине с Intel/AMD GPU настоящие вернули бы True)
cfg_loc = S(device="auto", compute_type="auto", model="large-v3")
b2 = select_backend(cfg_loc, cuda_probe=lambda: False, ov_probe=lambda: False,
                    amd_probe=lambda: False)
ok &= check("auto+no-cuda -> CTranslate2Backend/cpu",
            isinstance(b2, CTranslate2Backend) and b2.device == "cpu"
            and b2.model_id == "small")
ok &= check("device_label для cpu", b2.device_label == "CPU")

# model_kind: CT2 -> "ct2" (вид модели для model_store.ensure_downloaded)
ok &= check("CTranslate2Backend.model_kind == ct2",
            CTranslate2Backend("small", "cpu", "int8").model_kind == "ct2")

# ── OV-адаптеры (чистые функции, без openvino) ────────────────
from reku.backends import ov_lang_token, chunks_to_segments, make_ov_info, OV_MODEL_MAP

ok &= check("ov_lang_token ru", ov_lang_token("ru") == "<|ru|>")
ok &= check("ov_lang_token пусто -> None", ov_lang_token("") is None)

_chunks = [S(text=" Привет ", start_ts=0.0, end_ts=1.2),
           S(text="мир", start_ts=1.2, end_ts=2.0)]
_segs = chunks_to_segments(_chunks)
ok &= check("chunks_to_segments: 2 сегмента", len(_segs) == 2)
ok &= check("chunks_to_segments: контракт .text/.start/.end/.compression_ratio",
            _segs[0].text == " Привет " and _segs[0].start == 0.0
            and _segs[1].end == 2.0 and _segs[0].compression_ratio > 0.0)

# compression_ratio считается честно (zlib, как в faster-whisper):
# зацикленный мусор жмётся сильно -> ratio высокий -> фильтр postprocess сработает
_loop = chunks_to_segments([S(text="и так " * 50, start_ts=0.0, end_ts=20.0)])
_norm = chunks_to_segments([S(text="обычная осмысленная фраза без повторов",
                              start_ts=0.0, end_ts=3.0)])
ok &= check("compression_ratio: зацикленный текст > 2.4 (порог фильтра)",
            _loop[0].compression_ratio > 2.4)
ok &= check("compression_ratio: обычный текст < 2.4",
            0.0 < _norm[0].compression_ratio < 2.4)
ok &= check("chunks_to_segments: пусто", chunks_to_segments([]) == [])
ok &= check("chunks_to_segments: None", chunks_to_segments(None) == [])

_info = make_ov_info("ru", 3.5)
ok &= check("make_ov_info: контракт info",
            _info.language == "ru" and _info.language_probability == 1.0
            and _info.duration == 3.5)

ok &= check("OV_MODEL_MAP: large-v3 и turbo",
            OV_MODEL_MAP["large-v3"] == "OpenVINO/whisper-large-v3-int8-ov"
            and OV_MODEL_MAP["large-v3-turbo"] == "OpenVINO/whisper-large-v3-turbo-int8-ov"
            and OV_MODEL_MAP["turbo"] == OV_MODEL_MAP["large-v3-turbo"])

# ── OpenVINOBackend: свойства и понятная ошибка про неизвестную модель ──
_ovb = OpenVINOBackend(model="large-v3", device="igpu")
ok &= check("OV device_label GPU", _ovb.device_label == "Intel GPU (OpenVINO)")
ok &= check("OV model_kind", _ovb.model_kind == "ov")
ok &= check("OV model_id -> репо", _ovb.model_id == "OpenVINO/whisper-large-v3-int8-ov")
ok &= check("OV npu label",
            OpenVINOBackend(model="large-v3", device="npu").device_label
            == "Intel NPU (OpenVINO)")
try:
    OpenVINOBackend(model="no-such-model", device="igpu").load()
    ok &= check("OV.load: ValueError для неизвестной модели", False)
except ValueError as e:
    ok &= check("OV.load: ValueError для неизвестной модели", "no-such-model" in str(e))

# ── OpenVINOBackend.transcribe: фейковый пайплайн, без железа ──
import numpy as np


class _FakePipe:
    def generate(self, samples, **kw):
        assert isinstance(samples, list), "generate ждёт list[float]"
        return S(chunks=[S(text="тест", start_ts=0.0, end_ts=1.0)])


_ovb2 = OpenVINOBackend(model="large-v3", device="igpu")
_ovb2._pipe = _FakePipe()
_cfg = S(language="ru", vad_filter=False, initial_prompt="", beam_size=5,
         condition_on_previous_text=False, no_repeat_ngram_size=3)
_segs2, _info2 = _ovb2.transcribe(np.zeros(16000, dtype=np.float32), _cfg)
ok &= check("OV.transcribe: сегменты через адаптер",
            len(_segs2) == 1 and _segs2[0].text == "тест")
ok &= check("OV.transcribe: info.language_probability=1.0",
            _info2.language_probability == 1.0 and _info2.duration == 1.0)

# ── apply_vad: тишина -> None (реальный Silero из faster-whisper) ──
from reku.backends import apply_vad

ok &= check("apply_vad: тишина -> None",
            apply_vad(np.zeros(16000, dtype=np.float32)) is None)

# apply_vad: «речь» моком faster_whisper.vad
import faster_whisper.vad as _fwvad

_orig_get, _orig_collect = _fwvad.get_speech_timestamps, _fwvad.collect_chunks
_fwvad.get_speech_timestamps = lambda audio, **kw: [{"start": 0, "end": 8000}]
_fwvad.collect_chunks = lambda audio, chunks, **kw: ([audio[:8000]], [{}])
try:
    _out = apply_vad(np.ones(16000, dtype=np.float32))
    ok &= check("apply_vad: речь -> склеенные куски",
                _out is not None and len(_out) == 8000)
finally:
    _fwvad.get_speech_timestamps, _fwvad.collect_chunks = _orig_get, _orig_collect


# VAD-гейт в transcribe: нет речи -> пустой результат без вызова generate
class _BoomPipe:
    def generate(self, *a, **kw):
        raise AssertionError("generate не должен зваться при пустом VAD")


_ovb3 = OpenVINOBackend(model="large-v3", device="igpu")
_ovb3._pipe = _BoomPipe()
_cfg_vad = S(language="ru", vad_filter=True, initial_prompt="", beam_size=5,
             condition_on_previous_text=False, no_repeat_ngram_size=3)
_segs3, _info3 = _ovb3.transcribe(np.zeros(16000, dtype=np.float32), _cfg_vad)
ok &= check("OV.transcribe: VAD-гейт (тишина -> пусто, generate не зван)",
            _segs3 == [] and _info3.duration == 1.0)

# ── маршрутизация igpu/npu ────────────────────────────────────
from reku.backends import IGPU_AUTO_SUBSTITUTE, HEAVY_MODELS

# auto: cuda главнее igpu
ok &= check("auto+cuda(+ov) -> cuda",
            resolve_runtime("auto", "auto", "large-v3",
                            cuda_available=True, ov_gpu_available=True)
            == ("cuda", "float16", "large-v3"))

# auto: нет cuda, есть Intel GPU -> igpu; подстановка модели по карте ворот
_expected_mdl = IGPU_AUTO_SUBSTITUTE.get("large-v3", "large-v3")
ok &= check("auto+no-cuda+ov -> igpu (+карта ворот)",
            resolve_runtime("auto", "auto", "large-v3",
                            cuda_available=False, ov_gpu_available=True)
            == ("igpu", "int8", _expected_mdl))

# auto: лёгкая модель на igpu не трогается
ok &= check("auto+ov+light -> igpu/base",
            resolve_runtime("auto", "auto", "base",
                            cuda_available=False, ov_gpu_available=True)
            == ("igpu", "int8", "base"))

# карта подстановки понижает только тяжёлые
ok &= check("IGPU_AUTO_SUBSTITUTE только про HEAVY_MODELS",
            set(IGPU_AUTO_SUBSTITUTE) <= HEAVY_MODELS)

# auto: ничего нет -> cpu + понижение (существующее поведение, без нового kwarg)
ok &= check("auto+ничего -> cpu/small (совместимость)",
            resolve_runtime("auto", "auto", "large-v3", cuda_available=False)
            == ("cpu", "int8", "small"))

# явный igpu: probe не нужен, модель не понижается
ok &= check("явный igpu без понижения",
            resolve_runtime("igpu", "auto", "large-v3", cuda_available=False)
            == ("igpu", "int8", "large-v3"))

# явный npu
ok &= check("явный npu",
            resolve_runtime("npu", "auto", "large-v3", cuda_available=False)
            == ("npu", "int8", "large-v3"))

# select_backend: no-cuda + ov -> OpenVINOBackend igpu
_b_ov = select_backend(S(device="auto", compute_type="auto", model="base"),
                       cuda_probe=lambda: False, ov_probe=lambda: True,
                       amd_probe=lambda: False)
ok &= check("select: auto -> OpenVINOBackend/igpu",
            isinstance(_b_ov, OpenVINOBackend) and _b_ov.device == "igpu"
            and _b_ov.model_name == "base")

# select_backend: явный igpu не зовёт пробы
_probe_calls = []
_b_igpu = select_backend(S(device="igpu", compute_type="auto", model="large-v3"),
                         cuda_probe=lambda: _probe_calls.append("cuda") or False,
                         ov_probe=lambda: _probe_calls.append("ov") or False)
ok &= check("select: явный igpu без проб",
            isinstance(_b_igpu, OpenVINOBackend) and _probe_calls == [])

# select_backend: cuda есть -> ov/amd-пробы не зовутся (ленивость)
_ov_calls = []
_b_cuda = select_backend(S(device="auto", compute_type="auto", model="small"),
                         cuda_probe=lambda: True,
                         ov_probe=lambda: _ov_calls.append("ov") or True,
                         amd_probe=lambda: _ov_calls.append("amd") or True)
ok &= check("select: cuda найден -> ov/amd-пробы не званы",
            isinstance(_b_cuda, CTranslate2Backend) and _ov_calls == [])

# select_backend прокидывает поддерживаемые картой типы в resolve_runtime
_b_pascal = select_backend(S(device="auto", compute_type="auto", model="large-v3"),
                           cuda_probe=lambda: True,
                           cuda_types_probe=lambda: {"int8", "int8_float32", "float32"})
ok &= check("select: auto+pascal -> int8_float32",
            isinstance(_b_pascal, CTranslate2Backend)
            and _b_pascal.compute_type == "int8_float32")

# явный cuda: device-пробы не зовутся, но типы карты спрашиваются
_b_exp = select_backend(S(device="cuda", compute_type="auto", model="medium"),
                        cuda_probe=lambda: _probe_calls.append("cuda2") or False,
                        cuda_types_probe=lambda: {"float32"})
ok &= check("select: явный cuda+auto compute -> float32, без device-проб",
            isinstance(_b_exp, CTranslate2Backend)
            and _b_exp.compute_type == "float32" and "cuda2" not in _probe_calls)

# ── cpu_fallback_backend: запасной CPU-бэкенд для auto при сбое OV ──
from reku.backends import cpu_fallback_backend

_fb = cpu_fallback_backend(S(model="large-v3", compute_type="auto"))
ok &= check("cpu_fallback: тяжёлая -> small/cpu/int8",
            isinstance(_fb, CTranslate2Backend) and _fb.model_name == "small"
            and _fb.device == "cpu" and _fb.compute_type == "int8")
_fb2 = cpu_fallback_backend(S(model="base", compute_type="auto"))
ok &= check("cpu_fallback: лёгкая не понижается", _fb2.model_name == "base")

# ── dictate.load_model: auto + сбой OV -> фолбэк на CPU; явный igpu -> ошибка наружу ──
from reku import dictate
from reku import config as _config
from reku import model_store as _ms


class _FailingOV(OpenVINOBackend):
    def load(self):
        raise RuntimeError("compile boom")


class _OkCPU(CTranslate2Backend):
    loads = []

    def load(self):
        _OkCPU.loads.append(self.model_name)


_orig_select = backends.select_backend
_orig_fb = backends.cpu_fallback_backend
_orig_cached = _ms.is_cached
backends.select_backend = lambda cfg, **kw: _FailingOV("large-v3", "igpu")
backends.cpu_fallback_backend = lambda cfg: _OkCPU("small", "cpu", "int8")
_ms.is_cached = lambda m: True
try:
    _app = dictate.DictationApp(_config.Config())        # device=auto
    _app.load_model()
    ok &= check("auto: OV упал -> CPU-фолбэк загружен",
                isinstance(_app.backend, _OkCPU) and _OkCPU.loads == ["small"])

    _cfg_igpu = _config.Config()
    _cfg_igpu.device = "igpu"
    _app2 = dictate.DictationApp(_cfg_igpu)
    try:
        _app2.load_model()
        ok &= check("явный igpu: ошибка не глотается", False)
    except RuntimeError:
        ok &= check("явный igpu: ошибка не глотается", True)
finally:
    backends.select_backend = _orig_select
    backends.cpu_fallback_backend = _orig_fb
    _ms.is_cached = _orig_cached

# CTranslate2Backend.transcribe пробрасывает hotwords (пусто -> None, иначе строка)
captured = {}


class _FakeModel:
    def transcribe(self, audio, **kw):
        captured.update(kw)
        return iter([]), S(language="ru", language_probability=0.9)


b3 = CTranslate2Backend(model="small", device="cpu", compute_type="int8")
b3._model = _FakeModel()
_cfg_hw = S(lang_or_none="ru", beam_size=5, vad_filter=True, initial_prompt="P",
            condition_on_previous_text=False, no_repeat_ngram_size=3, hotwords="PostgreSQL, Redis")
b3.transcribe(None, _cfg_hw)
ok &= check("hotwords проброшен в transcribe", captured.get("hotwords") == "PostgreSQL, Redis")

captured.clear()
_cfg_no = S(lang_or_none="ru", beam_size=5, vad_filter=True, initial_prompt="P",
            condition_on_previous_text=False, no_repeat_ngram_size=3, hotwords="")
b3.transcribe(None, _cfg_no)
ok &= check("пустой hotwords -> None", captured.get("hotwords") is None)

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
