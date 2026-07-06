"""Бенч бэкендов Reku: скорость/качество на реальном железе.

Standalone-диагностика (в приложение не импортируется), запуск из корня репозитория:
  python scripts/bench_backends.py record   — надиктовать эталонные фразы (WAV 16 кГц)
  python scripts/bench_backends.py run      — прогнать матрицу бэкендов, напечатать таблицу

WAV лежат в <data_dir>/bench_audio/. Результаты — bench_results.md там же.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import time
import wave

import numpy as np

from reku import config

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


# ── конфигурации бенча ──────────────────────────────────────────
INITIAL_PROMPT = ("Claude Code, GitHub, Docker, 1С, "
                  "faster-whisper, Postgres, OData.")
LANG = "ru"

# CT2 large-v3 исключена из матрицы: +3.1 ГБ докачки при слабом интернете,
# на CPU она заведомо мимо критерия скорости (см. план Task 3). small
# пропущена решением пользователя (2026-07-04). База сравнения CPU — turbo.
CT2_MODELS = ["large-v3-turbo"]
OV_REPOS = {
    "large-v3-turbo": "OpenVINO/whisper-large-v3-turbo-int8-ov",
    "large-v3": "OpenVINO/whisper-large-v3-int8-ov",
}
N_RUNS = 2   # 1-й прогон = холодный (компиляция/кэши), 2-й = честная скорость


def _bench_ct2(model_name: str, wavs: list) -> list[dict]:
    """CPU-путь как в приложении: faster-whisper int8, VAD, beam 5."""
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model
    download_model(model_name)          # скачивание вне замера load
    t0 = time.perf_counter()
    m = WhisperModel(model_name, device="cpu", compute_type="int8")
    load_s = time.perf_counter() - t0
    rows = []
    for path, audio in wavs:
        times, text = [], ""
        for _ in range(N_RUNS):
            t0 = time.perf_counter()
            segments, info = m.transcribe(
                audio, language=LANG, beam_size=5, vad_filter=True,
                initial_prompt=INITIAL_PROMPT,
                condition_on_previous_text=False, no_repeat_ngram_size=3)
            text = " ".join(s.text.strip() for s in segments)  # генератор: инференс тут
            times.append(time.perf_counter() - t0)
        rows.append(dict(engine=f"CPU-ct2/{model_name}", wav=os.path.basename(path),
                         dur=len(audio) / SR, load=load_s,
                         cold=times[0], warm=times[-1], text=text))
    del m
    return rows


def _ensure_ov_model(repo: str) -> str:
    """Качает OV-модель в раскладку model_store (та же папка, что у приложения).
    snapshot_download сам докачивает недостающие файлы (возобновляемо)."""
    from reku import model_store
    from huggingface_hub import snapshot_download
    path = model_store.model_path(repo)
    print(f"  модель {repo} -> {path}")
    snapshot_download(repo, local_dir=path)
    return path


def _bench_ov(model_name: str, repo: str, wavs: list) -> list[dict]:
    """iGPU-путь: OpenVINO GenAI WhisperPipeline. Эти вызовы — эталон для
    OpenVINOBackend (Task 6): kwargs generate() проверяются здесь живьём."""
    import openvino_genai
    path = _ensure_ov_model(repo)
    cache = os.path.join(config.data_dir(), "ov_cache")
    os.makedirs(cache, exist_ok=True)
    t0 = time.perf_counter()
    pipe = openvino_genai.WhisperPipeline(path, "GPU", CACHE_DIR=cache)
    load_s = time.perf_counter() - t0
    rows = []
    for path_w, audio in wavs:
        times, text = [], ""
        for _ in range(N_RUNS):
            t0 = time.perf_counter()
            result = pipe.generate(
                audio.tolist(), language=f"<|{LANG}|>", task="transcribe",
                return_timestamps=True, initial_prompt=INITIAL_PROMPT)
            chunks = getattr(result, "chunks", None) or []
            text = " ".join(c.text.strip() for c in chunks)
            times.append(time.perf_counter() - t0)
        rows.append(dict(engine=f"iGPU-ov/{model_name}", wav=os.path.basename(path_w),
                         dur=len(audio) / SR, load=load_s,
                         cold=times[0], warm=times[-1], text=text))
    del pipe
    return rows


def run() -> None:
    import glob
    paths = sorted(glob.glob(os.path.join(AUDIO_DIR, "*.wav")))
    if not paths:
        print("Нет WAV. Сначала: python bench_backends.py record")
        return
    wavs = [(p, load_wav(p)) for p in paths]
    rows = []
    for name in CT2_MODELS:
        print(f"\n=== CPU-ct2 / {name} ===")
        rows += _bench_ct2(name, wavs)
    for name, repo in OV_REPOS.items():
        print(f"\n=== iGPU-ov / {name} ===")
        rows += _bench_ov(name, repo, wavs)

    lines = ["| движок/модель | wav | длит., с | загрузка, с | 1-й прогон, с | повтор, с | RTF | текст |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['engine']} | {r['wav']} | {r['dur']:.1f} | {r['load']:.1f} "
                     f"| {r['cold']:.2f} | {r['warm']:.2f} | {r['warm'] / r['dur']:.2f} "
                     f"| {r['text']} |")
    table = "\n".join(lines)
    print("\n" + table)
    out = os.path.join(AUDIO_DIR, "bench_results.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Бенч {time.strftime('%Y-%m-%d %H:%M')}\n\n{table}\n")
    print(f"\nСохранено: {out}")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "record":
        record()
    elif cmd == "run":
        run()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
