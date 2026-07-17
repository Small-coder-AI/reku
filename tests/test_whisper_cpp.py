"""Тесты AMD-пути (whisper.cpp + Vulkan): чистые адаптеры, маршрутизация,
докачка движка — всё без сети (file://), GPU и настоящего whisper-server.
Запуск (из корня репозитория): python tests/test_whisper_cpp.py"""
import hashlib
import io
import os
import shutil
import sys
import tempfile
import wave
import zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from types import SimpleNamespace as S

from reku import whisper_cpp as wc
from reku import model_store as ms
from reku.backends import (WhisperCppBackend, WCPP_MODEL_MAP, resolve_runtime,
                           select_backend, OpenVINOBackend)


def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    return cond


ok = True

# ── карта моделей ─────────────────────────────────────────────
ok &= check("map: large-v3 -> q5_0-файл",
            WCPP_MODEL_MAP["large-v3"] == "ggml-large-v3-q5_0.bin")
ok &= check("map: turbo == large-v3-turbo",
            WCPP_MODEL_MAP["turbo"] == WCPP_MODEL_MAP["large-v3-turbo"])
ok &= check("map: покрывает те же имена, что и OV (без large-v2 разницы)",
            set(WCPP_MODEL_MAP) >= {"large-v3", "large-v3-turbo", "turbo",
                                    "medium", "small", "base", "tiny"})

# ── encode_wav: float32 -> mono/16bit WAV ─────────────────────
sig = (np.sin(np.linspace(0, 100, 16000)) * 0.5).astype(np.float32)
data = wc.encode_wav(sig)
with wave.open(io.BytesIO(data)) as w:
    ok &= check("wav: mono/16bit/16кГц/все сэмплы",
                w.getnchannels() == 1 and w.getsampwidth() == 2
                and w.getframerate() == 16000 and w.getnframes() == 16000)
# выбросы за [-1, 1] клиппятся, а не переполняются
_clip = wc.encode_wav(np.array([2.0, -2.0], dtype=np.float32))
with wave.open(io.BytesIO(_clip)) as w:
    _frames = np.frombuffer(w.readframes(2), dtype="<i2")
ok &= check("wav: клиппинг [-1,1]", _frames[0] == 32767 and _frames[1] == -32767)

# ── multipart: тело и Content-Type руками ─────────────────────
body, ctype = wc.encode_multipart({"language": "ru", "beam_size": 5}, b"RIFFxxxx")
ok &= check("multipart: Content-Type с boundary",
            ctype.startswith("multipart/form-data; boundary="))
_b = ctype.split("boundary=")[1]
ok &= check("multipart: поля, файл и закрывающий маркер",
            f"--{_b}".encode() in body and b'name="language"' in body
            and b'name="beam_size"' in body and b"RIFFxxxx" in body
            and body.endswith(f"\r\n--{_b}--\r\n".encode()))

# ── segments_from_response: контракт + свой compression_ratio ─
_resp = {"segments": [
    {"text": "и так " * 50, "start": 0.0, "end": 20.0, "no_speech_prob": 0.1},
    {"text": "обычная осмысленная фраза", "start": 20.0, "end": 22.0}]}
_segs = wc.segments_from_response(_resp)
ok &= check("segments: контракт .text/.start/.end",
            len(_segs) == 2 and _segs[1].text == "обычная осмысленная фраза"
            and _segs[0].start == 0.0 and _segs[1].end == 22.0)
ok &= check("segments: compression_ratio считаем сами (сервер не отдаёт)",
            _segs[0].compression_ratio > 2.4 > _segs[1].compression_ratio > 0.0)
ok &= check("segments: пустой ответ", wc.segments_from_response({}) == [])

# ── make_wcpp_info ────────────────────────────────────────────
_inf = wc.make_wcpp_info("ru", 3.0)
ok &= check("info: prob=None когда детекция не запрашивалась",
            _inf.language == "ru" and _inf.language_probability is None
            and _inf.duration == 3.0)
ok &= check("info: prob проброшен",
            wc.make_wcpp_info("ru", 1.0, 0.97).language_probability == 0.97)

# ── resolve_runtime: место amd в авто-цепочке ─────────────────
ok &= check("auto: cuda главнее amd",
            resolve_runtime("auto", "auto", "large-v3",
                            cuda_available=True, amd_available=True)
            == ("cuda", "float16", "large-v3"))
ok &= check("auto: amd раньше igpu",
            resolve_runtime("auto", "auto", "large-v3", cuda_available=False,
                            ov_gpu_available=True, amd_available=True)[0] == "amd")
ok &= check("auto+amd: тяжёлая модель НЕ понижается (8 ГБ VRAM тянут q5_0)",
            resolve_runtime("auto", "auto", "large-v3", cuda_available=False,
                            amd_available=True)[2] == "large-v3")
ok &= check("явный amd без проб",
            resolve_runtime("amd", "auto", "large-v3", cuda_available=False)[0]
            == "amd")
# модель без ggml-кванта в auto НЕ роняет AMD-путь в CPU: подстановка large-v3
ok &= check("auto+amd: distil-* подставляется large-v3 (GPU не теряется)",
            resolve_runtime("auto", "auto", "distil-large-v3",
                            cuda_available=False, amd_available=True)
            == ("amd", "int8", "large-v3"))
# явный amd подстановку НЕ делает — понятная ошибка в load() (решение пользователя)
ok &= check("явный amd: модель не подменяется",
            resolve_runtime("amd", "auto", "distil-large-v3",
                            cuda_available=False)[2] == "distil-large-v3")

# ── select_backend: маршрутизация и ленивость проб ────────────
_cfg = S(device="auto", compute_type="auto", model="large-v3")
_b = select_backend(
    _cfg, cuda_probe=lambda: False, amd_probe=lambda: True,
    ov_probe=lambda: (_ for _ in ()).throw(
        AssertionError("ov-проба не должна зваться, когда amd найден")))
ok &= check("select: auto+amd -> WhisperCppBackend",
            isinstance(_b, WhisperCppBackend) and _b.model_name == "large-v3")
_b_ctx = select_backend(S(device="amd", compute_type="auto", model="small"))
ok &= check("select: явный amd без проб",
            isinstance(_b_ctx, WhisperCppBackend) and _b_ctx.model_name == "small")
# amd найден, но CUDA главнее — и ov-проба не звана
_amd_calls = []
_b_cuda = select_backend(S(device="auto", compute_type="auto", model="small"),
                         cuda_probe=lambda: True,
                         amd_probe=lambda: _amd_calls.append(1) or True)
ok &= check("select: cuda найден -> amd-проба не звана", _amd_calls == [])
# amd нет -> цепочка идёт дальше в ov
_b_ov = select_backend(S(device="auto", compute_type="auto", model="base"),
                       cuda_probe=lambda: False, amd_probe=lambda: False,
                       ov_probe=lambda: True)
ok &= check("select: no-amd -> OpenVINOBackend", isinstance(_b_ov, OpenVINOBackend))

# ── свойства бэкенда и понятная ошибка про модель ─────────────
ok &= check("model_kind == ggml", _b.model_kind == "ggml")
ok &= check("model_id -> имя ggml-файла", _b.model_id == "ggml-large-v3-q5_0.bin")
ok &= check("device_label до load", _b.device_label == "GPU (Vulkan)")
_b._vk_devices = 0
ok &= check("device_label честен при 0 Vulkan-устройств",
            _b.device_label == "CPU (Vulkan не найден)")
try:
    WhisperCppBackend(model="no-such-model").load()
    ok &= check("load: ValueError для неизвестной модели", False)
except ValueError as e:
    ok &= check("load: ValueError для неизвестной модели", "no-such-model" in str(e))

# ── transcribe: поля запроса и VAD-гейт (сервер мокается) ─────
class _FakeServer:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def alive(self):
        return True

    def inference(self, wav, fields, timeout=300.0):
        self.calls.append((wav, dict(fields)))
        return self.resp


_bt = WhisperCppBackend(model="large-v3")
_bt._server = _FakeServer({"segments": [{"text": "тест", "start": 0, "end": 1}]})
_cfg_t = S(language="ru", vad_filter=False, initial_prompt="Промпт.", beam_size=5,
           min_language_probability=0.0)
_segs_t, _info_t = _bt.transcribe(np.zeros(16000, dtype=np.float32), _cfg_t)
_wav_sent, _fields_sent = _bt._server.calls[0]
ok &= check("transcribe: сегмент через адаптер",
            len(_segs_t) == 1 and _segs_t[0].text == "тест")
ok &= check("transcribe: поля language/beam_size/prompt/verbose_json",
            _fields_sent["language"] == "ru" and _fields_sent["beam_size"] == 5
            and _fields_sent["prompt"] == "Промпт."
            and _fields_sent["response_format"] == "verbose_json")
ok &= check("transcribe: фильтр выключен -> детекция языка отключена, prob=None",
            _fields_sent.get("no_language_probabilities") == "true"
            and _info_t.language_probability is None)
ok &= check("transcribe: WAV с RIFF-заголовком", _wav_sent[:4] == b"RIFF")

# включённый фильтр -> запрашиваем детекцию и пробрасываем вероятность
_bt2 = WhisperCppBackend(model="large-v3")
_bt2._server = _FakeServer({"segments": [{"text": "тест"}],
                            "detected_language": "ru",
                            "detected_language_probability": 0.93})
_cfg_p = S(language="ru", vad_filter=False, initial_prompt="", beam_size=5,
           min_language_probability=0.6)
_segs_p, _info_p = _bt2.transcribe(np.zeros(16000, dtype=np.float32), _cfg_p)
_, _fields_p = _bt2._server.calls[0]
ok &= check("transcribe: фильтр включён -> детекция запрошена, prob=0.93",
            "no_language_probabilities" not in _fields_p
            and _info_p.language_probability == 0.93 and _info_p.language == "ru")


class _BoomServer:
    def alive(self):
        return True

    def inference(self, *a, **kw):
        raise AssertionError("inference не должен зваться при пустом VAD")


_bt3 = WhisperCppBackend(model="large-v3")
_bt3._server = _BoomServer()
_cfg_v = S(language="ru", vad_filter=True, initial_prompt="", beam_size=5,
           min_language_probability=0.0)
_segs_v, _info_v = _bt3.transcribe(np.zeros(16000, dtype=np.float32), _cfg_v)
ok &= check("transcribe: VAD-гейт (тишина -> пусто, запроса нет)",
            _segs_v == [] and _info_v.duration == 1.0)


# ── автоперезапуск умершего сервера ───────────────────────────
import urllib.error


class _DeadThenOkServer:
    """Мёртв, пока не «перезапустят»: рестарт GPU-драйвера, антивирус и т.п."""

    def __init__(self):
        self.restarts = 0
        self._up = False

    def alive(self):
        return self._up

    def stop(self):
        self._up = False

    def start(self, timeout=180.0):
        self.restarts += 1
        self._up = True

    def inference(self, wav, fields, timeout=300.0):
        if not self._up:
            raise urllib.error.URLError("connection refused")
        return {"segments": [{"text": "ожил", "start": 0, "end": 1}]}


_bt4 = WhisperCppBackend(model="large-v3")
_bt4._server = _DeadThenOkServer()
_segs_r, _ = _bt4.transcribe(np.zeros(16000, dtype=np.float32), _cfg_t)
ok &= check("transcribe: мёртвый сервер перезапущен, результат получен",
            _bt4._server.restarts == 1 and len(_segs_r) == 1
            and _segs_r[0].text == "ожил")


class _AlwaysDeadServer(_DeadThenOkServer):
    def start(self, timeout=180.0):
        self.restarts += 1          # «поднялся», но запросы всё равно падают

    def inference(self, wav, fields, timeout=300.0):
        raise urllib.error.URLError("connection refused")


_bt5 = WhisperCppBackend(model="large-v3")
_bt5._server = _AlwaysDeadServer()
try:
    _bt5.transcribe(np.zeros(16000, dtype=np.float32), _cfg_t)
    ok &= check("transcribe: два падения подряд -> ошибка наружу", False)
except urllib.error.URLError:
    ok &= check("transcribe: два падения подряд -> ошибка наружу",
                _bt5._server.restarts == 2)   # мёртв + ретрай после URLError

# _server=None (гонка с reload_model) -> понятная ошибка, не AttributeError
_bt6 = WhisperCppBackend(model="large-v3")
try:
    _bt6.transcribe(np.zeros(16000, dtype=np.float32), _cfg_t)
    ok &= check("transcribe: _server=None -> RuntimeError", False)
except RuntimeError as e:
    ok &= check("transcribe: _server=None -> RuntimeError", "не загружена" in str(e))

# ── ensure_engine: распаковка + sha256, всё через file:// ─────
_tmp = tempfile.mkdtemp(prefix="reku_wcpp_test_")
_zip = os.path.join(_tmp, "engine.zip")
with zipfile.ZipFile(_zip, "w") as z:
    z.writestr("whisper-server.exe", b"fake server")
    z.writestr("whisper-cli.exe", b"fake cli")
    z.writestr("LICENSE.whisper.cpp.txt", b"MIT")
_sha = hashlib.sha256(open(_zip, "rb").read()).hexdigest()

_orig = (wc.ENGINE_URL, wc.ENGINE_SHA256, wc.engine_dir)
os.environ.pop("REKU_WHISPER_CPP_DIR", None)
wc.ENGINE_URL = "file:///" + _zip.replace("\\", "/")
wc.ENGINE_SHA256 = _sha
wc.engine_dir = lambda: os.path.join(_tmp, "engine")
try:
    _exe = wc.ensure_engine()
    ok &= check("ensure_engine: распаковано, exe на месте",
                os.path.isfile(_exe) and open(_exe, "rb").read() == b"fake server")
    ok &= check("ensure_engine: повторный вызов не качает заново",
                wc.ensure_engine() == _exe)
    ok &= check("ensure_engine: временный zip убран",
                not os.path.exists(os.path.join(_tmp, "engine") + ".zip.tmp"))
    # битая сумма -> понятная ошибка, недокачка не остаётся
    shutil.rmtree(os.path.join(_tmp, "engine"))
    wc.ENGINE_SHA256 = "0" * 64
    try:
        wc.ensure_engine()
        ok &= check("ensure_engine: sha256 mismatch -> ошибка", False)
    except RuntimeError as e:
        ok &= check("ensure_engine: sha256 mismatch -> ошибка",
                    "sha256" in str(e))
    ok &= check("ensure_engine: после сбоя каталог движка не создан",
                not os.path.exists(os.path.join(_tmp, "engine")))
finally:
    wc.ENGINE_URL, wc.ENGINE_SHA256, wc.engine_dir = _orig

# REKU_WHISPER_CPP_DIR: явный оверрайд не докачивает молча
_dev_dir = os.path.join(_tmp, "devbuild")
os.makedirs(_dev_dir)
os.environ["REKU_WHISPER_CPP_DIR"] = _dev_dir
try:
    try:
        wc.ensure_engine()
        ok &= check("оверрайд без exe -> FileNotFoundError", False)
    except FileNotFoundError:
        ok &= check("оверрайд без exe -> FileNotFoundError", True)
    open(os.path.join(_dev_dir, "whisper-server.exe"), "wb").write(b"dev")
    ok &= check("оверрайд с exe -> используется он",
                wc.ensure_engine() == os.path.join(_dev_dir, "whisper-server.exe"))
finally:
    del os.environ["REKU_WHISPER_CPP_DIR"]

# ── model_store: одиночный ggml-файл считается кэшем ──────────
_orig_dd = ms._data_dir
ms._data_dir = lambda: _tmp
try:
    ok &= check("is_cached: ggml-файла нет -> False",
                not ms.is_cached("ggml-tiny-q5_1.bin"))
    os.makedirs(os.path.join(_tmp, "models"), exist_ok=True)
    open(os.path.join(_tmp, "models", "ggml-tiny-q5_1.bin"), "wb").write(b"x")
    ok &= check("is_cached: одиночный ggml-файл -> True",
                ms.is_cached("ggml-tiny-q5_1.bin"))
finally:
    ms._data_dir = _orig_dd

# ── ServerProcess: ранняя смерть процесса даёт понятную ошибку ─
_log = os.path.join(_tmp, "server.log")
_sp = wc.ServerProcess(sys.executable, "no_such_module_xyz", log_path=_log)
try:
    _sp.start(timeout=60)
    ok &= check("ServerProcess: ранняя смерть -> RuntimeError", False)
    _sp.stop()
except RuntimeError as e:
    ok &= check("ServerProcess: ранняя смерть -> RuntimeError",
                "whisper-server" in str(e) and "server.log" in str(e))
ok &= check("ServerProcess: лог сервера записан",
            os.path.isfile(_log) and os.path.getsize(_log) > 0)

shutil.rmtree(_tmp, ignore_errors=True)

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
