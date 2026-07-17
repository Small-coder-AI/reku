"""Механика AMD-пути (whisper.cpp + Vulkan): движок, серверный процесс, HTTP-клиент.

Сам бэкенд (WhisperCppBackend) живёт в backends.py и дёргает этот модуль. Здесь:
  - ensure_engine(): докачка НАШЕГО CI-билда whisper-server (релиз
    engine-whisper-cpp-*-vulkan этого репозитория) с проверкой sha256;
  - ServerProcess: запуск whisper-server подпроцессом, ожидание /health,
    /inference-запросы, гарантированная остановка (Job Object + atexit);
  - encode_wav()/encode_multipart()/segments_from_response()/make_wcpp_info():
    чистые адаптеры, тестируются без сети и железа (tests/test_whisper_cpp.py).

Почему подпроцесс, а не python-биндинги: официальных Windows-бинарников
whisper.cpp с Vulkan нет, pywhispercpp пришлось бы собирать из исходников на
машине пользователя. Готовый статически слинкованный whisper-server.exe + HTTP
на 127.0.0.1 — меньше движущихся частей, и модель живёт в VRAM между
диктовками (whisper-cli грузил бы ~1 ГБ на каждую фразу).

Весь модуль — стандартная библиотека: AMD-профиль install.ps1 не тянет
дополнительных python-пакетов.
"""
import atexit
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
import wave
import zipfile

# Пин движка: тег нашего служебного релиза + sha256 архива (см. workflow
# build-whisper-cpp.yml). При обновлении движка менять все три константы разом.
ENGINE_TAG = "engine-whisper-cpp-v1.9.1-vulkan"
ENGINE_ZIP = "whisper-cpp-vulkan-v1.9.1-win-x64.zip"
ENGINE_URL = ("https://github.com/Small-coder-AI/reku/releases/download/"
              f"{ENGINE_TAG}/{ENGINE_ZIP}")
ENGINE_SHA256 = "51c060fdd0668f7e444fecc092827377dc10d5cacc83f2ff274848fe69444408"
SERVER_EXE = "whisper-server.exe"


# ── движок: где лежит и как докачать ─────────────────────────────

def engine_dir() -> str:
    """Каталог движка. REKU_WHISPER_CPP_DIR — оверрайд для разработки (локальная
    сборка whisper.cpp); иначе data_dir/engines/<тег> — версионируем по тегу,
    чтобы обновление движка не затирало рабочий, пока не докачается новый."""
    override = os.environ.get("REKU_WHISPER_CPP_DIR")
    if override:
        return override
    from reku import config  # лениво: тесты подменяют engine_dir целиком
    return os.path.join(config.data_dir(), "engines", ENGINE_TAG)


def server_exe_path() -> str:
    return os.path.join(engine_dir(), SERVER_EXE)


def _download(url: str, dest: str) -> None:
    with urllib.request.urlopen(url) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def _verify_sha256(path: str, expected: str) -> None:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest().lower() != expected.lower():
        os.remove(path)   # битую/подменённую скачку не оставляем
        raise RuntimeError(f"sha256 движка не совпал: ожидал {expected}, "
                           f"получил {h.hexdigest()} ({ENGINE_URL})")


def ensure_engine(on_progress=None) -> str:
    """Гарантирует наличие whisper-server.exe локально, возвращает путь к нему.
    Докачка атомарная: распаковка во временный каталог + os.replace, как у
    моделей в model_store. on_progress(имя) зовётся раз перед скачиванием."""
    exe = server_exe_path()
    if os.path.isfile(exe):
        return exe
    if os.environ.get("REKU_WHISPER_CPP_DIR"):
        # явный оверрайд не докачиваем молча — разработчик указал СВОЮ сборку
        raise FileNotFoundError(f"REKU_WHISPER_CPP_DIR задан, но {exe} не найден")
    if on_progress:
        on_progress(ENGINE_ZIP)
    d = engine_dir()
    os.makedirs(os.path.dirname(d), exist_ok=True)
    zpath = d + ".zip.tmp"
    _download(ENGINE_URL, zpath)
    _verify_sha256(zpath, ENGINE_SHA256)
    tmp = d + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmp)
    os.remove(zpath)
    shutil.rmtree(d, ignore_errors=True)
    os.replace(tmp, d)
    if not os.path.isfile(exe):
        raise FileNotFoundError(f"в архиве движка нет {SERVER_EXE} ({ENGINE_URL})")
    return exe


# ── чистые адаптеры (без сети и железа) ──────────────────────────

def encode_wav(audio, sample_rate: int = 16000) -> bytes:
    """float32 [-1..1] -> WAV (mono, 16-бит PCM) в памяти. 16-бит, а не float32:
    его понимает любой WAV-ридер, а точности хватает — микрофоны и так 16-бит."""
    import numpy as np
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def encode_multipart(fields: dict, file_bytes: bytes,
                     file_name: str = "audio.wav") -> tuple[bytes, str]:
    """multipart/form-data вручную: стандартная библиотека его не собирает,
    а тянуть requests ради одного запроса не хочется. Возвращает (тело,
    значение заголовка Content-Type с boundary)."""
    boundary = "----reku-" + uuid.uuid4().hex
    lines = []
    for k, v in fields.items():
        lines += [f"--{boundary}",
                  f'Content-Disposition: form-data; name="{k}"', "", str(v)]
    lines += [f"--{boundary}",
              f'Content-Disposition: form-data; name="file"; filename="{file_name}"',
              "Content-Type: audio/wav", ""]
    head = ("\r\n".join(lines) + "\r\n").encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("ascii")
    return head + file_bytes + tail, f"multipart/form-data; boundary={boundary}"


def segments_from_response(resp: dict) -> list:
    """verbose_json сервера -> сегменты контракта faster-whisper. Наш postprocess
    читает .text и .compression_ratio; сервер compression_ratio не отдаёт
    («not implemented yet» в server.cpp v1.9.1), поэтому считаем сами — тем же
    zlib-способом, что и в OV-пути (иначе фильтр «пересжатых» сегментов мёртв)."""
    from types import SimpleNamespace
    from reku.backends import _compression_ratio
    out = []
    for s in (resp.get("segments") or []):
        text = s.get("text", "")
        out.append(SimpleNamespace(
            text=text, start=s.get("start"), end=s.get("end"),
            compression_ratio=_compression_ratio(text),
            no_speech_prob=s.get("no_speech_prob")))
    return out


def make_wcpp_info(language, duration, probability=None):
    """info контракта faster-whisper. probability=None — когда доп. проход
    детекции языка не запрашивался: dictate трактует None как «фильтр
    min_language_probability не применим» (в отличие от OV-пути, где всегда 1.0)."""
    from types import SimpleNamespace
    return SimpleNamespace(language=language or "",
                           language_probability=probability, duration=duration)


def display_adapter_names() -> list[str]:
    """Имена активных видеоадаптеров через EnumDisplayDevicesW (user32, ctypes).
    Только реально присутствующие устройства — в реестре остаются следы давно
    вынутых карт; и без подпроцессов (CIM-запрос PowerShell стоил бы ~1-2 с
    на каждый старт в auto-режиме)."""
    import ctypes
    from ctypes import wintypes

    class DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD),
                    ("DeviceName", ctypes.c_wchar * 32),
                    ("DeviceString", ctypes.c_wchar * 128),
                    ("StateFlags", wintypes.DWORD),
                    ("DeviceID", ctypes.c_wchar * 128),
                    ("DeviceKey", ctypes.c_wchar * 128)]

    names, i = [], 0
    while True:
        dev = DISPLAY_DEVICEW()
        dev.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        if not ctypes.windll.user32.EnumDisplayDevicesW(None, i, ctypes.byref(dev), 0):
            break
        if dev.DeviceString:
            names.append(dev.DeviceString)
        i += 1
    return list(dict.fromkeys(names))   # дедуп с сохранением порядка


# ── серверный процесс ────────────────────────────────────────────

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _kill_on_parent_death(proc) -> None:
    """Привязывает подпроцесс к Job Object с KILL_ON_JOB_CLOSE: даже при жёстком
    убийстве приложения (Task Manager) ОС закроет job и прибьёт whisper-server.
    Иначе осиротевший сервер держал бы ~1 ГБ VRAM до перезагрузки. Страховка
    best-effort: при сбое остаётся обычная остановка через atexit/stop()."""
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32

        class BASIC_LIMITS(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class EXTENDED_LIMITS(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC_LIMITS),
                        ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        job = k32.CreateJobObjectW(None, None)
        if not job:
            return
        info = EXTENDED_LIMITS()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        # 9 = JobObjectExtendedLimitInformation
        k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        k32.AssignProcessToJobObject(job, wintypes.HANDLE(int(proc._handle)))
        proc._reku_job = job   # хэндл живёт с процессом: закрыли хэндл -> умер job
    except Exception:
        pass


class ServerProcess:
    """Жизненный цикл whisper-server: запуск -> готовность (/health) ->
    /inference-запросы -> остановка. Лог сервера пишется в файл: по нему видно,
    нашёл ли ggml Vulkan-устройства или тихо укатился на CPU (урок CUDA-пути:
    тихий откат на CPU выглядит как «просто медленно работает»)."""

    def __init__(self, exe: str, model_path: str, *, log_path: str | None = None):
        self.exe = exe
        self.model_path = model_path
        self.log_path = log_path
        self.port = None
        self._proc = None
        self._log_f = None

    def start(self, timeout: float = 180.0) -> None:
        self.port = _free_port()
        # контекст между 30-секундными окнами сервер v1.9.1 НЕ переносит сам:
        # в server.cpp захардкожено no_context=true (флага/поля нет вообще) —
        # это ровно наш дефолт condition_on_previous_text=False; включить
        # перенос контекста на этом пути нельзя (осознанное ограничение)
        args = [self.exe, "-m", self.model_path,
                "--host", "127.0.0.1", "--port", str(self.port)]
        creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW: без консоли под pythonw
        self._log_f = (open(self.log_path, "w", encoding="utf-8", errors="replace")
                       if self.log_path else subprocess.DEVNULL)
        self._proc = subprocess.Popen(args, stdout=self._log_f,
                                      stderr=subprocess.STDOUT,
                                      creationflags=creationflags)
        _kill_on_parent_death(self._proc)
        atexit.register(self.stop)
        self._wait_ready(timeout)

    def _wait_ready(self, timeout: float) -> None:
        """Ждёт 200 от /health (503 = модель ещё грузится в VRAM). Раннюю смерть
        процесса (нет vulkan-1.dll, битая модель) отличаем от долгой загрузки."""
        deadline = time.monotonic() + timeout
        url = f"http://127.0.0.1:{self.port}/health"
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                code = self._proc.returncode
                self.stop()
                raise RuntimeError(
                    f"whisper-server завершился при старте (код {code}); "
                    f"лог: {self.log_path}")
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    if r.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                pass   # ещё не слушает порт либо 503 «loading model»
            time.sleep(0.3)
        self.stop()
        raise TimeoutError(f"whisper-server не поднялся за {timeout:.0f} с; "
                           f"лог: {self.log_path}")

    def inference(self, wav_bytes: bytes, fields: dict,
                  timeout: float = 300.0) -> dict:
        """POST /inference; fields — поля формы (language, beam_size, prompt...).
        Таймаут щедрый: длинная диктовка на CPU-фолбэке может считаться минуты."""
        body, ctype = encode_multipart(fields, wav_bytes)
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/inference",
            data=body, headers={"Content-Type": ctype})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def vulkan_devices(self):
        """Сколько Vulkan-устройств нашёл ggml (по логу сервера); None = не разобрать.
        0 — движок молча работает на CPU: это надо показать пользователю."""
        if not self.log_path or not os.path.isfile(self.log_path):
            return None
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = re.search(r"[Ff]ound (\d+) Vulkan devices", line)
                    if m:
                        return int(m.group(1))
        except OSError:
            pass
        return None

    def stop(self) -> None:
        atexit.unregister(self.stop)
        p, self._proc = self._proc, None
        if p is not None and p.poll() is None:
            p.terminate()   # состояния сервер не хранит — TerminateProcess безопасен
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        if self._log_f not in (None, subprocess.DEVNULL):
            try:
                self._log_f.close()
            except Exception:
                pass
        self._log_f = None
