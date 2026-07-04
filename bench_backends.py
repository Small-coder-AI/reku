"""Бенч бэкендов whisper_ptt: скорость/качество на реальном железе.

Standalone-диагностика (в приложение не импортируется):
  python bench_backends.py record   — надиктовать эталонные фразы (WAV 16 кГц)
  python bench_backends.py run      — прогнать матрицу бэкендов, напечатать таблицу

WAV лежат в <data_dir>/bench_audio/. Результаты — bench_results.md там же.
"""
import os
import sys
import time
import wave

import numpy as np

import config

SR = 16000
AUDIO_DIR = os.path.join(config.data_dir(), "bench_audio")


def wav_path(i: int) -> str:
    return os.path.join(AUDIO_DIR, f"phrase_{i:02d}.wav")


def save_wav(path: str, audio: np.ndarray) -> None:
    """float32 [-1..1] -> WAV int16 mono 16 кГц."""
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def load_wav(path: str) -> np.ndarray:
    """WAV int16 mono -> float32 [-1..1]."""
    with wave.open(path, "rb") as w:
        assert w.getframerate() == SR, f"{path}: ожидался {SR} Гц"
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def record() -> None:
    """Интерактивная запись фраз: Enter — старт, Enter — стоп."""
    import sounddevice as sd
    os.makedirs(AUDIO_DIR, exist_ok=True)
    print("Запись эталонных фраз (16 кГц). Советую 3–5 фраз: короткую (~3 с),")
    print("среднюю (~7 с), длинную (~15 с). Ввод 'q' — выход.\n")
    i = 1
    while os.path.exists(wav_path(i)):
        i += 1  # не затирать уже записанные
    while True:
        if input(f"Фраза {i}: Enter — начать запись (или 'q' + Enter — выход): ").strip():
            break
        frames = []
        stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                                callback=lambda d, n, t, s: frames.append(d.copy()))
        stream.start()
        input("● Говори... Enter — стоп: ")
        stream.stop(); stream.close()
        if not frames:
            print("Пусто, повтор.\n")
            continue
        audio = np.concatenate(frames).flatten()
        save_wav(wav_path(i), audio)
        print(f"  Сохранено: {wav_path(i)} ({len(audio) / SR:.1f} с)\n")
        i += 1


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "record":
        record()
    elif cmd == "run":
        print("run: см. Task 3")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
