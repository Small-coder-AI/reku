"""Тест политики transcribe (порог языка + постпроцессинг) на фейковом бэкенде.
GPU не нужен. Запуск: python test_transcribe_pipeline.py"""
import numpy as np
from types import SimpleNamespace as S
import config
from dictate import DictationApp


def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    return cond


def seg(text, cr=1.0):
    return S(text=text, compression_ratio=cr)


class FakeBackend:
    device_label = "CPU"
    model_id = None
    def __init__(self, segments, lang="ru", lang_p=0.9):
        self._segs = segments
        self._info = S(language=lang, language_probability=lang_p)
    def load(self):
        pass
    def transcribe(self, audio, cfg):
        return iter(self._segs), self._info


ok = True
audio = np.zeros(16000, dtype=np.float32)

# нормальная речь проходит, фантом вырезается
cfg = config.Config(min_language_probability=0.0)
app = DictationApp(cfg)
app.backend = FakeBackend([seg("привет мир"), seg("Thank you for watching!")])
ok &= check("текст распознан, фантом вырезан", app.transcribe(audio) == "привет мир")

# низкая вероятность языка -> подавление (пусто)
cfg2 = config.Config(min_language_probability=0.5)
app2 = DictationApp(cfg2)
app2.backend = FakeBackend([seg("привет")], lang_p=0.2)
ok &= check("низкий language_probability -> пусто", app2.transcribe(audio) == "")

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
