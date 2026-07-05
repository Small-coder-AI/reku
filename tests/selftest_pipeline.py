"""Headless-проверка пайплайна: config -> model -> transcribe -> filter.
Клавиатуру/вставку не трогает. Запуск (из корня репозитория):
python tests/selftest_pipeline.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from reku import config
from reku.dictate import DictationApp, parse_hotkey

# 1. конфиг и парс хоткея
cfg = config.load()
print("hotkey parse ctrl_r:", parse_hotkey("ctrl_r"))
print("hotkey parse 'q':", parse_hotkey("q"))
print("mode:", cfg.mode, "| vad:", cfg.vad_filter,
      "| condition_prev:", cfg.condition_on_previous_text,
      "| no_repeat_ngram:", cfg.no_repeat_ngram_size)

# 2. модель + пайплайн
app = DictationApp(cfg)
app.load_model()
print("backend:", app.backend.name, "| device:", app.backend.device_label)

sr = cfg.sample_rate
silence = np.zeros(sr * 3, dtype=np.float32)
noise = (0.01 * np.random.randn(sr * 3)).astype(np.float32)

print("\n[silence] ->", repr(app.transcribe(silence)))   # ждём '' (VAD режет)
print("[noise]   ->", repr(app.transcribe(noise)))       # ждём '' (VAD режет)
print("\nOK: пайплайн отработал без исключений.")
