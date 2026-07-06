"""
Диагностика GPU vs CPU инференса для faster-whisper / CTranslate2.

Использование:
    python diag.py cpu          # baseline на CPU
    python diag.py cuda         # CUDA без фикса DLL-путей
    python diag.py cuda --fix   # CUDA + os.add_dll_directory(nvidia\\*\\bin)

Печатает: время загрузки модели, время ПЕРВОГО прогона (включает JIT/autotune),
время ВТОРОГО прогона (steady-state). Если первый медленный, а второй быстрый —
это не CPU, а разовая компиляция ядер. Если оба медленные — реально CPU.
"""
import os
import sys
import time

device = "cuda"
compute = "float16"
fix = "--fix" in sys.argv
if "cpu" in sys.argv:
    device = "cpu"
    compute = "int8"  # на CPU float16 не имеет смысла

# --- ФИКС DLL-путей: строго ДО импорта faster_whisper ---
# mode: "" (нет), "dll" (add_dll_directory), "path" (PATH), "both"
fix_mode = ""
if "--dll" in sys.argv:
    fix_mode = "dll"
elif "--path" in sys.argv:
    fix_mode = "path"
elif "--both" in sys.argv:
    fix_mode = "both"
elif fix:
    fix_mode = "both"

if fix_mode:
    # резолв через find_spec — корректно и в venv, и в глобальном окружении
    # (os.__file__ в venv указывает на базовый Lib, а не на venv — так нельзя)
    import importlib.util
    _spec = importlib.util.find_spec("nvidia")
    nvidia = _spec.submodule_search_locations[0] if _spec and _spec.submodule_search_locations else ""
    bin_dirs = []
    if nvidia and os.path.isdir(nvidia):
        for name in os.listdir(nvidia):
            p = os.path.join(nvidia, name, "bin")
            if os.path.isdir(p):
                bin_dirs.append(p)
    for p in bin_dirs:
        if fix_mode in ("dll", "both"):
            os.add_dll_directory(p)
        if fix_mode in ("path", "both"):
            os.environ["PATH"] = p + os.pathsep + os.environ["PATH"]
    print(f"[fix={fix_mode}] dirs: {bin_dirs}")

import numpy as np
from faster_whisper import WhisperModel

print(f"\n=== device={device} compute={compute} fix={fix} ===")

t = time.perf_counter()
model = WhisperModel("large-v3", device=device, compute_type=compute)
print(f"load: {time.perf_counter()-t:.2f}s")

# Тестовое аудио: 4 секунды. Тон 220 Гц + лёгкий шум, чтобы VAD не вырезал всё
# и энкодер+декодер реально отработали (нам важно само время, не текст).
sr = 16000
n = sr * 4
tone = 0.1 * np.sin(2 * np.pi * 220 * np.arange(n) / sr)
noise = 0.01 * np.random.randn(n)
audio = (tone + noise).astype(np.float32)

def run(tag):
    t = time.perf_counter()
    segs, info = model.transcribe(audio, beam_size=5, vad_filter=False,
                                   language="ru")
    text = " ".join(s.text for s in segs)  # форсируем генератор
    dt = time.perf_counter() - t
    print(f"{tag}: {dt:.2f}s  (lang={info.language}, text_len={len(text)})")
    return dt

try:
    run("прогон-1 (с JIT)")
    run("прогон-2 (steady)")
    run("прогон-3 (steady)")
except Exception as e:
    print(f"!!! ИСКЛЮЧЕНИЕ при transcribe: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
