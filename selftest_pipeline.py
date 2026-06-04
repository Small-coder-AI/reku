"""Headless-проверка пайплайна: config -> model -> transcribe -> filter.
Клавиатуру/вставку не трогает. Запуск: python selftest_pipeline.py"""
import numpy as np
import config
from dictate import DictationApp, parse_hotkey

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

sr = cfg.sample_rate
silence = np.zeros(sr * 3, dtype=np.float32)
noise = (0.01 * np.random.randn(sr * 3)).astype(np.float32)

print("\n[silence] ->", repr(app.transcribe(silence)))   # ждём '' (VAD режет)
print("[noise]   ->", repr(app.transcribe(noise)))       # ждём '' (VAD режет)
print("\nOK: пайплайн отработал без исключений.")
