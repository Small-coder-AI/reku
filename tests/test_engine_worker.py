"""Рабочий поток хоткея (Фаза 0): слушатель клавиш встаёт независимо от результата
первой загрузки модели, повторная загрузка по хоткею/request_load(), колбэки хука
только ставят команды в очередь и не блокируются на PortAudio/загрузке/друг друге.

Реальные клавиатура, микрофон и GPU не нужны: pynput/sounddevice — стабы окружения,
здесь дополнительно подменены keyboard.Listener, аудиопоток, бэкенд и вставка текста.
Запуск (из корня репозитория): python tests/test_engine_worker.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
import time
from types import SimpleNamespace as S

import numpy as np

from reku import config
from reku import backends
from reku import dictate
from reku.dictate import DictationApp


def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    return cond


def wait_until(predicate, timeout=3.0, interval=0.01):
    """Опрос вместо фиксированных sleep — рабочий поток асинхронный, фиксированная
    пауза либо дребезжит, либо зря удлиняет тесты."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# ── фейки: клавиатура, аудиопоток, бэкенды ───────────────────────────────
class FakeListener:
    """Подменяет pynput.keyboard.Listener: реальной клавиатуры не трогает, но
    хранит on_press/on_release — тест дёргает их напрямую, имитируя хук."""
    def __init__(self, on_press=None, on_release=None):
        self.on_press = on_press
        self.on_release = on_release
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def join(self):
        pass


dictate.keyboard.Listener = FakeListener


class FakeStream:
    def __init__(self, cb):
        self.cb = cb
        self.closed = False
        self.stopped = False

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class FakeBackend:
    """Успешная загрузка, мгновенный load()."""
    device_label = "CPU"
    model_id = None
    name = "fake"

    def load(self):
        pass

    def transcribe(self, audio, cfg):
        return (iter([S(text="текст", compression_ratio=1.0)]),
                S(language="ru", language_probability=1.0))


class SlowTranscribeBackend(FakeBackend):
    """Распознавание занимает заметное время — окно для проверки, что запрос на
    старт во время транскрибации не откладывается на потом."""
    def __init__(self, delay):
        self.delay = delay

    def transcribe(self, audio, cfg):
        time.sleep(self.delay)
        return super().transcribe(audio, cfg)


class FailingBackend:
    """Загрузка падает — симулирует сбой первой загрузки модели."""
    device_label = "CPU"
    model_id = None
    name = "fake"

    def load(self):
        raise RuntimeError("симулированный сбой загрузки")

    def transcribe(self, audio, cfg):
        raise AssertionError("не должно вызываться")


def make_app(mode="ptt", open_delay=0.0):
    """Готовое приложение с подменённым Listener/стримом/вставкой. select_backend
    подменяется в самом тесте — разным сценариям нужны разные исходы загрузки."""
    cfg = config.Config()
    cfg.mode = mode
    app = DictationApp(cfg)
    run = S(states=[], inserted=[], results=[], streams=[])
    app.on_state = run.states.append
    app.on_result = run.results.append
    app.insert = run.inserted.append          # настоящий Ctrl+V в тесте недопустим

    def open_stream(cb):
        if open_delay:
            time.sleep(open_delay)
        s = FakeStream(cb)
        run.streams.append(s)
        return s

    app._open_stream = open_stream
    run.app = app
    return run


_orig_select = backends.select_backend

ok = True

# ── 1. сбой первой загрузки -> слушатель всё равно встал ────────────────
backends.select_backend = lambda cfg: FailingBackend()
r1 = make_app(mode="ptt")
app1 = r1.app
app1.start()
ok &= check("сбой первой загрузки: слушатель стартует сразу, не ждёт загрузку",
            app1._listener is not None and app1._listener.started)
ok &= check("сбой первой загрузки: сбой осел (backend=None, не loading)",
            wait_until(lambda: app1._last_error is not None and not app1.loading))
backends.select_backend = _orig_select

ok &= check("сбой первой загрузки: backend не установлен", app1.backend is None)
ok &= check("сбой первой загрузки: состояние error", bool(r1.states) and r1.states[-1] == "error")
ok &= check("сбой первой загрузки: слушатель не остановлен", not app1._listener.stopped)

# ── 2a. после сбоя: нажатие хоткея догружает модель, слушатель тот же ────
worker_before = app1._worker
listener_before = app1._listener
backends.select_backend = lambda cfg: FakeBackend()
app1._listener.on_press(app1.hotkey)
app1._listener.on_release(app1.hotkey)
ok &= check("ретрай хоткеем: модель догрузилась",
            wait_until(lambda: app1.backend is not None and not app1.loading))
backends.select_backend = _orig_select

ok &= check("ретрай хоткеем: состояние idle", r1.states[-1] == "idle")
ok &= check("ретрай хоткеем: слушатель не пересоздан", app1._listener is listener_before)
ok &= check("ретрай хоткеем: рабочий поток тот же (без перезапуска приложения)",
            app1._worker is worker_before)
app1.stop()

# ── 2b. request_load() тоже догружает модель после сбоя ──────────────────
backends.select_backend = lambda cfg: FailingBackend()
r2 = make_app(mode="ptt")
app2 = r2.app
app2.start()
ok &= check("request_load(): сбой первой загрузки осел",
            wait_until(lambda: app2._last_error is not None and not app2.loading))
backends.select_backend = _orig_select
ok &= check("request_load(): backend всё ещё None после сбоя", app2.backend is None)

backends.select_backend = lambda cfg: FakeBackend()
app2.request_load()
ok &= check("request_load(): backend появился после явного запроса",
            wait_until(lambda: app2.backend is not None and not app2.loading))
backends.select_backend = _orig_select
ok &= check("request_load(): состояние idle", r2.states[-1] == "idle")
ok &= check("request_load(): слушатель цел", app2._listener is not None and not app2._listener.stopped)
app2.stop()

# ── 3. _on_press не блокируется на медленном открытии стрима ─────────────
backends.select_backend = lambda cfg: FakeBackend()
r3 = make_app(mode="ptt", open_delay=1.0)
app3 = r3.app
app3.start()
ok &= check("медленный стрим: модель загрузилась", wait_until(lambda: app3.backend is not None))
backends.select_backend = _orig_select

t0 = time.perf_counter()
app3._listener.on_press(app3.hotkey)
dt = time.perf_counter() - t0
ok &= check(f"медленный стрим: _on_press вернулся за {dt * 1000:.0f} мс (< 50 мс)", dt < 0.05)

ok &= check("медленный стрим: запись всё же стартовала в рабочем потоке",
            wait_until(lambda: app3._recording, timeout=3.0))
app3._listener.on_release(app3.hotkey)
ok &= check("медленный стрим: после отпускания дошли до idle",
            wait_until(lambda: r3.states[-1] == "idle", timeout=3.0))
app3.stop()

# ── 4. PTT: авто-повтор ОС при удержании -> ровно одна запись ────────────
backends.select_backend = lambda cfg: FakeBackend()
r4 = make_app(mode="ptt")
app4 = r4.app
app4.start()
ok &= check("ptt авто-повтор: модель загрузилась", wait_until(lambda: app4.backend is not None))
backends.select_backend = _orig_select

for _ in range(5):                      # имитация повторных on_press при удержании клавиши
    app4._listener.on_press(app4.hotkey)
ok &= check("ptt авто-повтор: запись началась", wait_until(lambda: app4._recording, timeout=2.0))
app4._listener.on_release(app4.hotkey)
ok &= check("ptt авто-повтор: дошли до idle", wait_until(lambda: r4.states[-1] == "idle", timeout=2.0))
ok &= check("ptt авто-повтор: микрофон открыт ровно один раз", len(r4.streams) == 1)
app4.stop()

# ── 5. toggle: press -> старт, press -> стоп ──────────────────────────────
backends.select_backend = lambda cfg: FakeBackend()
r5 = make_app(mode="toggle")
app5 = r5.app
app5.start()
ok &= check("toggle: модель загрузилась", wait_until(lambda: app5.backend is not None))
backends.select_backend = _orig_select

app5._listener.on_press(app5.hotkey)
app5._listener.on_release(app5.hotkey)      # физическое отпускание — сбрасывает key_held
ok &= check("toggle: первое нажатие стартует запись", wait_until(lambda: app5._recording, timeout=2.0))

app5._listener.on_press(app5.hotkey)        # второе нажатие — стоп
app5._listener.on_release(app5.hotkey)
ok &= check("toggle: второе нажатие доходит до idle",
            wait_until(lambda: r5.states[-1] == "idle", timeout=2.0))
ok &= check("toggle: микрофон открыт ровно один раз (старт-стоп, не старт-старт)",
            len(r5.streams) == 1)
app5.stop()

# ── 6a. короткий тап (гонка start_rec/stop_and_transcribe напрямую) ──────
# existing orphan-guard в start_rec(): стрим, открывшийся ПОСЛЕ stop_and_transcribe,
# не должен остаться висеть открытым.
r6 = make_app(mode="ptt", open_delay=0.2)
app6 = r6.app
app6.backend = FakeBackend()
t = threading.Thread(target=app6.start_rec, daemon=True)
t.start()
ok &= check("короткий тап: start_rec вошёл в запись", wait_until(lambda: app6._recording, timeout=1.0))
app6.stop_and_transcribe()                  # «отпускание» с другого потока, стрим ещё открывается
t.join(timeout=2.0)

ok &= check("короткий тап: в приложении не остался открытый стрим", app6._stream is None)
ok &= check("короткий тап: если стрим успел открыться — он закрыт",
            all(s.closed for s in r6.streams) if r6.streams else True)
ok &= check("короткий тап: _recording сброшен", app6._recording is False)

# ── 6b. тот же короткий тап, но через очередь хоткея целиком ─────────────
backends.select_backend = lambda cfg: FakeBackend()
r6b = make_app(mode="ptt", open_delay=0.15)
app6b = r6b.app
app6b.start()
ok &= check("короткий тап через хоткей: модель загрузилась",
            wait_until(lambda: app6b.backend is not None))
backends.select_backend = _orig_select

app6b._listener.on_press(app6b.hotkey)
app6b._listener.on_release(app6b.hotkey)    # отпустили ещё до того, как стрим открылся
ok &= check("короткий тап через хоткей: команды осели, дошли до idle",
            wait_until(lambda: r6b.states[-1] == "idle", timeout=2.0))
ok &= check("короткий тап через хоткей: микрофон не остался открытым", app6b._stream is None)
app6b.stop()

# ── 7. нажатие во время распознавания игнорируется, а не откладывается ───
slow_backend = SlowTranscribeBackend(0.3)
backends.select_backend = lambda cfg: slow_backend
r7 = make_app(mode="ptt")
app7 = r7.app
app7.start()
ok &= check("нажатие во время распознавания: модель загрузилась",
            wait_until(lambda: app7.backend is not None))
backends.select_backend = _orig_select

app7._listener.on_press(app7.hotkey)
ok &= check("нажатие во время распознавания: запись стартовала",
            wait_until(lambda: app7._recording, timeout=2.0))
# без звука stop_and_transcribe() выходит до transcribe() (см. "if not self._frames") —
# кормим один блок, иначе медленный transcribe() ни разу не позовётся
app7._stream.cb(np.full((1600, 1), 0.01, dtype=np.float32), 1600, None, None)
app7._listener.on_release(app7.hotkey)      # запускает stop_and_transcribe (0.3 c) в рабочем потоке
ok &= check("нажатие во время распознавания: распознавание идёт",
            wait_until(lambda: app7._transcribing, timeout=2.0))

qsize_before = app7._cmd_queue.qsize()
app7.request_start()                        # «нажатие» во время распознавания
qsize_after = app7._cmd_queue.qsize()
ok &= check("нажатие во время распознавания: запрос НЕ встал в очередь",
            qsize_after == qsize_before)

ok &= check("нажатие во время распознавания: распознавание успешно закончилось",
            wait_until(lambda: not app7._transcribing, timeout=2.0))
time.sleep(0.2)   # если бы запрос всё же исполнился — новая запись успела бы начаться
ok &= check("нажатие во время распознавания: новая запись не началась сама по себе",
            app7._recording is False)
ok &= check("нажатие во время распознавания: микрофон открывался только один раз",
            len(r7.streams) == 1)
app7.stop()

# ── 8. stop() завершает рабочий поток, идемпотентен ───────────────────────
backends.select_backend = lambda cfg: FakeBackend()
r8 = make_app(mode="ptt")
app8 = r8.app
app8.start()
ok &= check("stop(): рабочий поток жив после старта",
            wait_until(lambda: app8._worker is not None and app8._worker.is_alive()))
backends.select_backend = _orig_select

app8.stop()
ok &= check("stop(): рабочий поток завершился",
            wait_until(lambda: not app8._worker.is_alive(), timeout=2.0))
ok &= check("stop(): слушатель остановлен", app8._listener.stopped)

try:
    app8.stop()
    idempotent = True
except Exception:
    idempotent = False
ok &= check("stop(): повторный вызов идемпотентен (не падает)", idempotent)

backends.select_backend = _orig_select

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
