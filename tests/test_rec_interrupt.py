"""Обрыв звука посреди записи: распознанный обрывок НЕ вставляется в окно молча.

Боевой случай 2026-09-14: единственный микрофон — Bluetooth-гарнитура (Hands-Free),
её конечная точка пропадает на 0.5–2 c до 19 раз в день. Звук на это время перестаёт
приходить (sounddevice при этом не бросает исключений: stop()/close() глотают ошибки
хоста), обрывок распознаётся и раньше вставлялся как обычный текст — «диктую одно,
вставляется несвязное». Теперь такой текст уходит в буфер обмена, а пользователь
видит причину.

Микрофон, GPU, клавиатура и настоящий буфер обмена не нужны: поток, часы, буфер и
вставка подменены. Запуск (из корня репозитория): python tests/test_rec_interrupt.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time as _real_time
from types import SimpleNamespace as S

import numpy as np

from reku import config
from reku import dictate
from reku.dictate import DictationApp


def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    return cond


class FakeClock:
    """Монотонные часы под управлением теста."""
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeStream:
    def __init__(self, cb):
        self.cb = cb

    def stop(self):
        pass

    def close(self):
        pass


class FakeBackend:
    device_label = "CPU"
    model_id = None
    name = "fake"

    def transcribe(self, audio, cfg):
        return (iter([S(text="обрывок фразы", compression_ratio=1.0)]),
                S(language="ru", language_probability=1.0))


clock = FakeClock()
clipboard = []
# подменяем только ссылки ВНУТРИ модуля dictate: время и буфер обмена процесса не трогаем
dictate.time = S(monotonic=clock, perf_counter=_real_time.perf_counter,
                 sleep=lambda s: None, strftime=_real_time.strftime)
dictate.pyperclip = S(copy=clipboard.append, paste=lambda: "")

SR = 16000
BLOCK = 1600                                # 0.1 c звука на блок
BLOCK_S = BLOCK / SR


def dictation(schedule, release_after=0.05, cfg=None, app=None):
    """Одна диктовка. schedule — паузы (c) перед каждым блоком звука; release_after —
    сколько прошло от последнего блока до отпускания клавиши."""
    cfg = cfg or config.Config()
    if app is None:
        app = DictationApp(cfg)
        app.backend = FakeBackend()
    run = S(states=[], inserted=[], results=[])
    app.on_state = run.states.append
    app.on_result = run.results.append
    app.insert = run.inserted.append          # настоящий Ctrl+V в тесте недопустим
    streams = []
    app._open_stream = lambda cb: streams.append(FakeStream(cb)) or streams[-1]
    clipboard.clear()

    app.start_rec()
    block = np.full((BLOCK, 1), 0.01, dtype=np.float32)
    for pause in schedule:
        clock.t += pause
        streams[0].cb(block, BLOCK, None, None)
    clock.t += release_after
    app.stop_and_transcribe()
    run.app = app
    run.clipboard = list(clipboard)
    return run


def steady(n):
    return [BLOCK_S] * n


ok = True

# 1. ровный поток — вставка как раньше
r = dictation(steady(30))
ok &= check("ровный поток: текст вставлен один раз", r.inserted == ["обрывок фразы"])
ok &= check("ровный поток: on_result вызван", r.results == ["обрывок фразы"])
ok &= check("ровный поток: итоговое состояние idle", r.states[-1] == "idle")

# 2. звук пропал на 1.5 c посреди записи — обрывок не вставляется
r = dictation(steady(10) + [1.5] + steady(10))
ok &= check("обрыв посреди записи: в окно НЕ вставлено", r.inserted == [])
ok &= check("обрыв посреди записи: текст в буфере обмена", r.clipboard == ["обрывок фразы"])
ok &= check("обрыв посреди записи: состояние error", r.states[-1] == "error")
ok &= check("обрыв посреди записи: причина для UI",
            "прерывался" in (r.app._last_error or "") and "буфер" in (r.app._last_error or ""))
ok &= check("обрыв посреди записи: «✓ вставлено» не показываем", r.results == [])

# 3. звук пропал и до отпускания клавиши не вернулся (устройство отвалилось насовсем)
r = dictation(steady(10), release_after=2.0)
ok &= check("обрыв в хвосте: в окно НЕ вставлено", r.inserted == [])
ok &= check("обрыв в хвосте: текст в буфере обмена", r.clipboard == ["обрывок фразы"])

# 4. следующая нормальная запись после обрыва снова вставляется (счётчики сброшены)
r2 = dictation(steady(20), app=r.app)
ok &= check("после обрыва: новая запись вставлена", r2.inserted == ["обрывок фразы"])
ok &= check("после обрыва: состояние снова idle", r2.states[-1] == "idle")

# 5. пауза на разгоне потока (первые 0.5 c) — старт устройства, а не обрыв
r = dictation([0.0, 1.5] + steady(20))
ok &= check("пауза на разгоне потока не считается обрывом", r.inserted == ["обрывок фразы"])

# 6. дрожание доставки ниже порога — не обрыв
r = dictation(steady(10) + [BLOCK_S + 0.3] + steady(10))
ok &= check("дрожание 0.3 c: текст вставлен", r.inserted == ["обрывок фразы"])

# 7. проверку можно выключить конфигом (0 = прежнее поведение)
cfg_off = config.Config()
cfg_off.max_audio_gap_s = 0
r = dictation(steady(10) + [1.5] + steady(10), cfg=cfg_off)
ok &= check("max_audio_gap_s=0: обрыв вставляется как раньше", r.inserted == ["обрывок фразы"])

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
