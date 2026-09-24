"""Reku — локальная диктовка по push-to-talk (голос → текст в активное окно).

Запуск:  python dictate.py
Настройки — в config.json (создаётся при первом запуске). См. config.py.

Импорт-безопасен: при импорте модуля приложение НЕ запускается (это делает трей).
"""
import sys

from reku import APP_NAME

# Мгновенный фидбек при старте (под pythonw stdout=None — поэтому guard).
if sys.stdout:
    print(f"{APP_NAME}: запускаюсь, гружу зависимости…", flush=True)

from reku import cuda_setup  # noqa: F401 — кладёт nvidia DLL в PATH, СТРОГО до faster_whisper

import time
import threading
import queue

import numpy as np
import sounddevice as sd
import pyperclip
from pynput import keyboard
from pynput.keyboard import Key, Controller, KeyCode

from reku import config
from reku import postprocess

# Инференс инкапсулирован в backends.py (faster_whisper грузится лениво там,
# строго после cuda_setup). DictationApp работает через self.backend.

# единый текст предупреждения (старт приложения и путь ошибки записи)
MIC_NOT_FOUND_MSG = "Микрофон не найден — подключи микрофон и нажми запись"

# Разгон потока: паузы в поступлении звука, начавшиеся в первые STREAM_WARMUP_S
# после первого блока, обрывом не считаем — это старт устройства (Bluetooth-гарнитура
# переключает профиль на Hands-Free), а не пропажа микрофона посреди фразы.
# Сам порог обрыва — config.max_audio_gap_s.
STREAM_WARMUP_S = 0.5


def mic_available() -> bool:
    """Есть ли в системе устройство записи. PortAudio снимает список устройств ОДИН
    раз при инициализации — микрофон, подключённый после старта приложения, без
    переинициализации невидим (запись падала бы с невнятным PaErrorCode -9999).
    Поэтому перед проверкой пересоздаём PortAudio. Дёргать только когда запись
    не идёт: _terminate() убил бы активный стрим."""
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass
    try:
        return any(d["max_input_channels"] > 0 for d in sd.query_devices())
    except Exception:
        return False


def parse_hotkey(name: str):
    """Имя из конфига -> объект pynput. 'ctrl_r' -> Key.ctrl_r; 'a' -> KeyCode('a')."""
    name = (name or "").strip()
    if hasattr(Key, name):
        return getattr(Key, name)
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    raise ValueError(f"неизвестный хоткей в config.json: {name!r} "
                     f"(ожидается имя Key.<...> или один символ)")


# Команды рабочего потока хоткея (см. DictationApp._worker_loop). Сравниваются по
# identity (object()), а не по значению — строки-команды тут не нужны.
_CMD_START = object()
_CMD_STOP = object()
_CMD_TOGGLE = object()
_CMD_LOAD = object()
_CMD_QUIT = object()


class DictationApp:
    """Ядро: запись -> распознавание -> вставка. UI (консоль/трей) цепляется
    через колбэки on_state(state) и on_result(text)."""

    STATES = ("loading", "downloading", "idle", "recording", "transcribing", "error")

    def __init__(self, cfg: config.Config, on_state=None, on_result=None, on_level=None):
        self.cfg = cfg
        try:
            self.hotkey = parse_hotkey(cfg.hotkey)
        except ValueError as e:           # битый хоткей в config.json не должен ронять старт
            print(f"[init] {e}; беру дефолт ctrl_r", file=sys.stderr)
            self.hotkey = parse_hotkey("ctrl_r")
        self.kb = Controller()
        self.backend = None
        self._last_error = None          # текст последней ошибки загрузки/записи (для UI)

        self._recording = False
        self._transcribing = False
        self._key_held = False          # дедуп авто-повтора ОС при удержании — общий для ptt и toggle
        self._frames = []
        self._stream = None
        # учёт поступления звука в текущей записи (монотонное время, c) — по нему
        # видно, что устройство замолкало посреди фразы (см. _audio_gap_s)
        self._first_cb_t = None
        self._last_cb_t = None
        self._last_block_s = 0.0
        self._max_gap_s = 0.0
        self._lock = threading.Lock()
        self._listener = None
        self._worker = None
        self._loading = False            # True, пока в рабочем потоке идёт (пере)загрузка модели
        self._cmd_queue = queue.Queue()  # команды хоткея -> рабочий поток (см. _worker_loop)

        self.on_state = on_state or self._print_state
        self.on_result = on_result or (lambda text: print(f"→ {text}\n", flush=True))
        self.on_level = on_level or (lambda rms: None)   # живой уровень звука для UI

    # ── статус по умолчанию (консоль) ────────────────────────
    @staticmethod
    def _print_state(state):
        msg = {"loading": "Загружаю модель (первый запуск ~5-10 c, не прерывай)...",
               "downloading": "Скачиваю модель (первый запуск, может занять минуты)...",
               "idle": None,
               "recording": "● запись...",
               "transcribing": "⏳ распознаю...",
               "error": "⚠ ошибка (см. stderr)"}.get(state)
        if msg:
            print(msg, flush=True)

    def _set_state(self, state):
        try:
            self.on_state(state)
        except Exception as e:  # колбэк UI не должен ронять ядро
            print(f"[on_state] {e}", file=sys.stderr)

    # ── загрузка модели ──────────────────────────────────────
    def load_model(self):
        """Грузит модель. Сбой OpenVINO в auto-режиме -> тихий откат на CPU
        (спека Фазы 2). При окончательном сбое (нет сети, OOM, битая модель,
        device='cuda' без GPU) НЕ виснет в loading: обнуляет backend, переводит
        UI в 'error' с текстом причины и пробрасывает исключение наверх."""
        from reku import backends
        try:
            self.backend = backends.select_backend(self.cfg)
            try:
                self._download_and_load()
            except Exception as e:
                # тихий откат на CPU — только в auto и только для GPU-бэкендов,
                # у которых есть смысл в запасном пути (OpenVINO, whisper.cpp/AMD)
                if not (self.cfg.device == "auto"
                        and isinstance(self.backend, (backends.OpenVINOBackend,
                                                      backends.WhisperCppBackend))):
                    raise
                print(f"[fallback] {self.backend.name} не поднялся ({e}); "
                      f"перехожу на CPU", file=sys.stderr, flush=True)
                self.backend = backends.cpu_fallback_backend(self.cfg)
                self._download_and_load()
            self._last_error = None
        except Exception as e:
            self.backend = None
            self._last_error = str(e)
            print(f"[load_model] не смог загрузить модель: {e}", file=sys.stderr)
            self._set_state("error")
            raise

    def _download_and_load(self):
        from reku import model_store
        mid = self.backend.model_id
        if mid and not model_store.is_cached(mid):
            self._set_state("downloading")
            model_store.ensure_downloaded(
                mid, kind=self.backend.model_kind,
                on_progress=lambda m: print(
                    f"Скачиваю модель '{m}' (первый запуск, может занять минуты)…",
                    flush=True))
        self._set_state("loading")
        t0 = time.perf_counter()
        self.backend.load()
        print(f"Модель '{mid or self.backend.name}' на {self.backend.device_label} "
              f"за {time.perf_counter() - t0:.1f} c.", flush=True)
        self._set_state("idle")

    # ── запись ───────────────────────────────────────────────
    def _open_stream(self, cb):
        """Открыть и запустить InputStream. Если .start() упал — закрыть уже
        созданный стрим (иначе течёт ресурс PortAudio) и пробросить исключение."""
        s = sd.InputStream(samplerate=self.cfg.sample_rate, channels=1,
                           dtype="float32", callback=cb)
        try:
            s.start()
        except Exception:
            try:
                s.close()
            except Exception:
                pass
            raise
        return s

    def start_rec(self):
        if self.backend is None:      # модель не загрузилась — писать нечем;
            self._set_state("error")  # _last_error уже хранит причину сбоя загрузки
            return
        with self._lock:
            if self._recording or self._transcribing:
                return
            self._recording = True
            self._frames = []
            self._first_cb_t = self._last_cb_t = None
            self._last_block_s = self._max_gap_s = 0.0

        sr = self.cfg.sample_rate

        def cb(indata, n, t, status):
            if self._recording:
                now = time.monotonic()
                last = self._last_cb_t
                if last is None:
                    self._first_cb_t = now
                elif last - self._first_cb_t >= STREAM_WARMUP_S:
                    # интервал между блоками сверх длины самого блока — звук не приходил
                    self._max_gap_s = max(self._max_gap_s, now - last - n / sr)
                self._last_cb_t = now
                self._last_block_s = n / sr
                self._frames.append(indata.copy())
                rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
                self.on_level(rms)

        # старт стрима может упасть (занятое/отсутствующее устройство, PortAudio):
        # откатываем флаг, иначе _recording залипнет True и запись больше не запустится
        try:
            self._stream = self._open_stream(cb)
        except Exception as first_err:
            err = first_err
            self._stream = None
            # mic_available() переинициализирует PortAudio: микрофон, подключённый
            # после старта приложения, только так и становится видим — если он
            # появился, вторая попытка открывает стрим без участия пользователя
            mic_ok = mic_available()
            if mic_ok:
                try:
                    self._stream = self._open_stream(cb)
                except Exception as retry_err:
                    err = retry_err
            if self._stream is None:
                self._recording = False
                self._last_error = str(err) if mic_ok else MIC_NOT_FOUND_MSG
                print(f"[start_rec] не смог открыть микрофон: {err}", file=sys.stderr)
                self._set_state("error")
                return
        # пока стрим открывался (ретрай с пере-инициализацией PortAudio — сотни мс),
        # мог прийти stop_and_transcribe (короткий тап PTT): он увидел _recording=True,
        # сбросил флаг и вышел (закрывать было нечего — self._stream ещё None). Без
        # перепроверки под локом остался бы вечно открытый стрим («горящий» микрофон)
        # и state recording при _recording=False.
        with self._lock:
            orphan = None
            if not self._recording:
                orphan, self._stream = self._stream, None
        if orphan is not None:
            try:
                orphan.stop()
                orphan.close()
            except Exception:
                pass
            return
        self._set_state("recording")

    def stop_and_transcribe(self):
        with self._lock:
            if not self._recording:
                return
            self._recording = False
            self._transcribing = True
        gap_s = self._audio_gap_s(time.monotonic())
        held_back = False
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
                self._stream = None
            if not self._frames:
                return
            audio = np.concatenate(self._frames, axis=0).flatten()
            self._set_state("transcribing")
            text = self.transcribe(audio)
            limit = self.cfg.max_audio_gap_s
            if limit and gap_s > limit:
                held_back = True
                self._hold_back(text, gap_s)
            elif text:
                self.insert(text)
                self.on_result(text)
            else:
                print("(пусто)\n", flush=True)
        finally:
            self._transcribing = False
            self._set_state("error" if held_back else "idle")

    def _audio_gap_s(self, now: float) -> float:
        """Самая длинная пауза в поступлении звука за текущую запись, c (сверх длины
        блока). Учитывает и хвост: звук перестал приходить и до отпускания клавиши
        так и не вернулся. Когда устройство пропадает (Bluetooth-гарнитура на 0.5–2 c),
        sounddevice молчит — stop()/close() глотают ошибки хоста, — поэтому обрыв
        виден только по времени между блоками."""
        last, first = self._last_cb_t, self._first_cb_t
        if last is None or last - first < STREAM_WARMUP_S:
            return self._max_gap_s
        return max(self._max_gap_s, now - last - self._last_block_s)

    def _hold_back(self, text: str, gap_s: float):
        """Запись прерывалась: распознанный обрывок в окно не вставляем — там он
        выглядит как несвязный текст. Кладём его в буфер обмена (вставить руками,
        если годится) и показываем причину через состояние 'error'."""
        copied = False
        if text:
            try:
                pyperclip.copy(text)
                copied = True
            except Exception as e:
                print(f"[hold_back] буфер обмена недоступен: {e}", file=sys.stderr)
        if copied:
            outcome = "текст не вставлен, он в буфере обмена (Ctrl+V)"
        elif text:
            outcome = "текст не вставлен"
        else:
            outcome = "распознать нечего"
        self._last_error = f"Звук с микрофона прерывался ({gap_s:.1f} c) — {outcome}"
        print(f"[rec] {self._last_error}\n", flush=True)

    # ── распознавание + фильтр ───────────────────────────────
    def transcribe(self, audio: np.ndarray) -> str:
        c = self.cfg
        t0 = time.perf_counter()
        segments, info = self.backend.transcribe(audio, c)
        # вторичный страж: на не-речи language_probability валится (~0.2).
        # is not None — другой бэкенд может не отдать вероятность (контракт не обязывает)
        lp = info.language_probability
        if c.min_language_probability and lp is not None and lp < c.min_language_probability:
            print(f"[filter] подавлено: lang={info.language} "
                  f"p={info.language_probability:.2f} < {c.min_language_probability}", flush=True)
            return ""
        texts = postprocess.clean_segments(
            segments,
            drop_hallucinations=c.drop_hallucinations,
            max_compression_ratio=c.max_compression_ratio,
        )
        text = postprocess.join_text(texts)
        dt = time.perf_counter() - t0
        p_str = f"{lp:.2f}" if lp is not None else "—"
        # время суток и длина звука — чтобы сопоставлять диктовку с событиями системы
        # (журнал Windows Audio: пропажи микрофона); текст в лог не пишем
        audio_s = len(audio) / c.sample_rate
        print(f"[{time.strftime('%H:%M:%S')} звук {audio_s:.1f}s → {dt:.2f}s, "
              f"lang={info.language} p={p_str}]", flush=True)
        return text

    # ── вставка в активное окно ──────────────────────────────
    def insert(self, text: str):
        if self.cfg.trailing_space:
            text = text + " "
        if self.cfg.insert_method == "type":
            self.kb.type(text)
            return
        # paste: через буфер обмена + Ctrl+V
        old = None
        if self.cfg.restore_clipboard:
            try:
                old = pyperclip.paste()
            except Exception:
                old = None
        pyperclip.copy(text)
        time.sleep(0.1)
        # Ctrl+V по ФИЗИЧЕСКОМУ коду клавиши V (0x56), а не по символу 'v':
        # press('v') зависит от активной раскладки — при русской раскладке символ
        # уходит как Unicode-ввод и НЕ комбинируется с Ctrl, поэтому вставка не
        # срабатывает (диагностика diag_paste.py: способ с 'v' падал, с VK — работал).
        # Микро-задержки между модификатором и клавишей — чтобы окно успело увидеть Ctrl.
        v_key = KeyCode.from_vk(0x56)
        self.kb.press(Key.ctrl); time.sleep(0.03)
        self.kb.press(v_key); time.sleep(0.03)
        self.kb.release(v_key); time.sleep(0.03)
        self.kb.release(Key.ctrl)
        time.sleep(0.1)
        if old is not None:
            try:
                pyperclip.copy(old)
            except Exception:
                pass

    # ── хоткей ───────────────────────────────────────────────
    def _matches(self, key) -> bool:
        if isinstance(self.hotkey, Key):
            return key == self.hotkey
        return getattr(key, "char", None) == getattr(self.hotkey, "char", object())

    def _on_press(self, key):
        """Колбэк pynput на потоке низкоуровневого хука клавиатуры (WH_KEYBOARD_LL
        на Windows): здесь нельзя ничего мало-мальски долгого (I/O, PortAudio,
        ожидание лока, занятого надолго) — если хук провисит дольше
        LowLevelHooksTimeout, Windows молча его снимет, и хоткей умрёт до
        перезапуска. Только ставим команду в очередь, исполняет её рабочий поток
        (_worker_loop)."""
        if not self._matches(key):
            return
        if self._key_held:            # авто-повтор ОС при удержании — не дублируем команду
            return
        self._key_held = True
        if self.cfg.mode == "toggle":
            self._request_start_like(_CMD_TOGGLE)
        else:  # ptt
            self.request_start()

    def _on_release(self, key):
        """Тот же поток хука и те же ограничения, что у _on_press."""
        if not self._matches(key):
            return
        self._key_held = False
        if self.cfg.mode == "ptt":
            self.request_stop()
        # toggle реагирует только на нажатие — отпускание ничего не ставит в очередь

    # ── очередь команд хоткея: потокобезопасно, неблокирующе ────
    def _enqueue(self, cmd):
        self._cmd_queue.put(cmd)

    def _request_start_like(self, cmd):
        """Общая точка для request_start() и toggle-нажатия: запрос во время
        распознавания не откладываем на потом — иначе команда осядет в очереди
        и выполнится уже ПОСЛЕ того, как распознавание закончится само по себе,
        незаметно для пользователя запустив новую запись."""
        if self._transcribing:
            return
        self._enqueue(cmd)

    def request_start(self):
        """«Начать запись»: потокобезопасно, неблокирующе, можно звать из любого
        потока (в т.ч. из хука клавиатуры). Если модель не загружена и загрузка
        сейчас не идёт — вместо записи запускает повторную попытку загрузки;
        если загрузка уже идёт — запрос игнорируется."""
        self._request_start_like(_CMD_START)

    def request_stop(self):
        """«Стоп и распознать»: потокобезопасно, неблокирующе. stop_and_transcribe()
        сам ничего не делает, если запись не идёт, — доп. проверка тут не нужна."""
        self._enqueue(_CMD_STOP)

    def request_load(self):
        """Повторить загрузку модели (после сбоя, или по внешнему запросу) —
        потокобезопасно, неблокирующе. Если загрузка уже идёт или модель уже
        загружена, рабочий поток команду тихо пропустит (см. _exec_retry_load)."""
        self._enqueue(_CMD_LOAD)

    @property
    def loading(self) -> bool:
        """True, пока в рабочем потоке идёт (пере)загрузка модели."""
        return self._loading

    # ── рабочий поток: выполняет команды хоткея по очереди, последовательно ─
    def _exec_start(self):
        if self.backend is None:
            self._exec_retry_load()
        else:
            self.start_rec()

    def _exec_toggle(self):
        """Решение старт/стоп принимается здесь, в рабочем потоке, по свежему
        self._recording, а не в потоке хука в момент нажатия — там оно могло
        устареть, пока команда стояла в очереди."""
        if self._recording:
            self.stop_and_transcribe()
        else:
            self._exec_start()

    def _exec_retry_load(self):
        """(Пере)загрузка модели в рабочем потоке: самая первая загрузка при
        старте и повтор по хоткею/request_load() после сбоя. Флаг _loading общий
        с reload_model() — не грузим модель второй раз поверх уже идущей загрузки
        (например хоткей во время смены модели в настройках)."""
        with self._lock:
            if self.backend is not None or self._loading:
                return
            self._loading = True
        try:
            self.load_model()
        except Exception:
            pass          # load_model() уже отразил сбой в _last_error и состоянии 'error'
        finally:
            self._loading = False

    def _dispatch(self, cmd):
        if cmd is _CMD_START:
            self._exec_start()
        elif cmd is _CMD_STOP:
            self.stop_and_transcribe()
        elif cmd is _CMD_TOGGLE:
            self._exec_toggle()
        elif cmd is _CMD_LOAD:
            self._exec_retry_load()

    def _worker_loop(self):
        # Проверка микрофона и первая загрузка модели — здесь, а не в start():
        # слушатель клавиш должен встать независимо от их результата, иначе
        # хоткей молчит до перезапуска после любого сбоя первой загрузки.
        mic_ok = mic_available()
        if not mic_ok:
            self._last_error = MIC_NOT_FOUND_MSG
            print("[start] микрофон не найден", file=sys.stderr, flush=True)
            self._set_state("error")
        self._exec_retry_load()
        if not mic_ok and not mic_available():
            # статусы загрузки модели успели перекрыть раннее предупреждение —
            # возвращаем его, если микрофон так и не появился
            self._last_error = MIC_NOT_FOUND_MSG
            self._set_state("error")
        while True:
            cmd = self._cmd_queue.get()
            if cmd is _CMD_QUIT:
                break
            try:
                self._dispatch(cmd)
            except Exception as e:
                # команда не должна убивать рабочий поток — иначе хоткей опять
                # «умирает» до перезапуска, ровно то, что чинит этот файл
                print(f"[worker] {type(e).__name__}: {e}", file=sys.stderr)

    def start(self):
        """Запускает рабочий поток и слушатель клавиш немедленно, не дожидаясь
        проверки микрофона и загрузки модели — они идут в рабочем потоке
        (_worker_loop). Не блокирует."""
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        mode_hint = ("нажми хоткей — старт, нажми снова — стоп"
                     if self.cfg.mode == "toggle" else "держи хоткей и говори")
        print(f"Готово. Режим: {self.cfg.mode} ({self.cfg.hotkey}). "
              f"{mode_hint}. Ctrl+C — выход.\n", flush=True)
        self._listener = keyboard.Listener(on_press=self._on_press,
                                            on_release=self._on_release)
        self._listener.start()

    def run(self):
        """Консольный запуск: стартует и блокируется до выхода."""
        self.start()
        self._listener.join()

    def stop(self):
        """Останавливает слушатель клавиш и рабочий поток. Идемпотентен."""
        if self._listener is not None:
            self._listener.stop()
        self._enqueue(_CMD_QUIT)

    def apply_config(self):
        """Перечитать настройки, влияющие на live-поведение (хоткей). Режим/язык
        читаются в обработчиках на каждое нажатие, их перечитывать не нужно."""
        try:
            self.hotkey = parse_hotkey(self.cfg.hotkey)
        except ValueError as e:
            print(f"[apply_config] {e}", file=sys.stderr)

    def reload_model(self):
        """Перезагрузка модели (после смены model/device/compute). Зови в фоне."""
        with self._lock:
            if self._recording or self._transcribing:
                return False
            self.backend = None
            self._loading = True         # см. _exec_retry_load: не грузить поверх этого
        try:
            self.load_model()
        finally:
            self._loading = False
        return True


def main():
    cfg = config.load()
    app = DictationApp(cfg)
    try:
        app.run()
    except KeyboardInterrupt:
        print("\nВыход.")
        sys.exit(0)


if __name__ == "__main__":
    main()
