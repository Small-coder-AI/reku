"""Диагностика галлюцинаций large-v3 на тишине/шуме.
Печатает сегменты + их метрики (no_speech_prob, avg_logprob, compression_ratio)
для разных входов и наборов параметров. Цель — увидеть, чем галлюцинация
отличается от речи по метрикам, чтобы пороги были обоснованы.
"""
import os, importlib.util
spec = importlib.util.find_spec("nvidia")
root = spec.submodule_search_locations[0]
for n in os.listdir(root):
    b = os.path.join(root, n, "bin")
    if os.path.isdir(b):
        os.environ["PATH"] = b + os.pathsep + os.environ["PATH"]

import numpy as np
from faster_whisper import WhisperModel

m = WhisperModel("large-v3", device="cuda", compute_type="float16")
sr = 16000

def make(kind, sec=4):
    n = sr * sec
    if kind == "silence":
        return np.zeros(n, dtype=np.float32)
    if kind == "quiet_noise":
        return (0.002 * np.random.randn(n)).astype(np.float32)
    if kind == "loud_noise":
        return (0.05 * np.random.randn(n)).astype(np.float32)
    if kind == "hum":  # 50 Гц фон + шум — типичный «не-речь, но не тишина»
        t = np.arange(n) / sr
        return (0.01 * np.sin(2 * np.pi * 50 * t) + 0.003 * np.random.randn(n)).astype(np.float32)

PROMPT = "Claude Code, Passivbot, Hyperliquid, 1С, faster-whisper, Keenetic, OData."

def run(tag, audio, **kw):
    segs, info = m.transcribe(audio, language=None, **kw)
    segs = list(segs)
    print(f"\n--- {tag}  (lang={info.language} p={info.language_probability:.2f}, n_seg={len(segs)}) ---")
    for s in segs:
        print(f"   no_speech={s.no_speech_prob:.3f}  avg_logprob={s.avg_logprob:.3f}  "
              f"comp_ratio={s.compression_ratio:.2f}  text={s.text!r}")

CUR = dict(beam_size=5, vad_filter=True, initial_prompt=PROMPT)  # текущие настройки
TUNED_NOVAD = dict(beam_size=5, vad_filter=False, initial_prompt=PROMPT,
                   condition_on_previous_text=False)
CUR_NOVAD = dict(beam_size=5, vad_filter=False, initial_prompt=PROMPT)

for kind in ("silence", "quiet_noise", "loud_noise", "hum"):
    a = make(kind)
    run(f"{kind} | ТЕКУЩИЕ (vad on)", a, **CUR)
    run(f"{kind} | vad OFF, condition=ON (default)", a, **CUR_NOVAD)
    run(f"{kind} | vad OFF, condition=OFF", a, **TUNED_NOVAD)
