"""A/B-проба настроек распознавания на ОДНОМ и том же аудио — чтобы глазами и
цифрами сравнить «латиницу внутри русских слов» между конфигами.

Запуск (записать ~18 c с микрофона и сравнить 3 конфига):
    .venv\\Scripts\\python.exe ab_test.py
На готовом аудио (wav/mp3/…):
    .venv\\Scripts\\python.exe ab_test.py path\\to\\audio.wav

Метрика «% смешанных слов» — слова, где в ОДНОМ токене есть и кириллица, и
латиница (это и есть симптом). Меньше = лучше. Печатает и сами расшифровки,
чтобы проверить, что бренды (Passivbot, OData) при этом не «обрусели».

Конфиги:
  A — как было: латинский initial_prompt, авто-язык (воспроизводит баг)
  B — русский язык + русский якорь, бренды в русской рамке промпта
  C — русский язык + чисто русский промпт, бренды в hotwords  (новый дефолт)
"""
import sys
import re

import cuda_setup  # noqa: F401 — кладёт nvidia-DLL в PATH СТРОГО до faster_whisper
from faster_whisper import WhisperModel
import config

CYR = re.compile(r"[А-Яа-яЁё]")
LAT = re.compile(r"[A-Za-z]")
BRANDS = "Claude Code, Passivbot, Hyperliquid, 1С, faster-whisper, Keenetic, OData."

COMMON = dict(beam_size=5, vad_filter=True,
              condition_on_previous_text=False, no_repeat_ngram_size=3)

CONFIGS = [
    ("A: латинский промпт, авто-язык (как было)",
     dict(language=None, initial_prompt=BRANDS, hotwords=None)),
    ("B: ru + русский якорь, бренды в рамке",
     dict(language="ru",
          initial_prompt="Это диктовка на русском языке. Возможны термины: " + BRANDS,
          hotwords=None)),
    ("C: ru + русский промпт + бренды в hotwords (новый дефолт)",
     dict(language="ru", initial_prompt="Это диктовка на русском языке.", hotwords=BRANDS)),
]


def mixed_stats(text):
    words = re.findall(r"\w+", text, flags=re.UNICODE)
    mixed = [w for w in words if CYR.search(w) and LAT.search(w)]
    pct = 100 * len(mixed) / max(len(words), 1)
    return len(mixed), len(words), pct, mixed


def get_audio():
    """np-массив (запись с микрофона) или путь к файлу (аргумент). transcribe ест оба."""
    if len(sys.argv) > 1:
        print(f"Беру аудио из файла: {sys.argv[1]}")
        return sys.argv[1]
    import sounddevice as sd
    secs = 18
    print(f"\n>>> Говори ~{secs} c по-РУССКИ с терминами "
          f"(репозиторий, HuggingFace, CUDA, опенсорс, Passivbot, бэкенд)…")
    print(">>> Запись пошла!")
    audio = sd.rec(int(secs * 16000), samplerate=16000, channels=1, dtype="float32")
    sd.wait()
    print(">>> Записал. Распознаю тремя конфигами (модель грузится ~6 c)…\n")
    return audio.flatten()


def main():
    audio = get_audio()
    cfg = config.load()        # устройство/точность из конфига — не падать на CPU-машинах
    model = WhisperModel("large-v3", device=cfg.device, compute_type=cfg.compute_type)
    print("=" * 72)
    for name, kw in CONFIGS:
        segs, info = model.transcribe(audio, **COMMON, **kw)
        text = " ".join(s.text for s in segs).strip()
        nmix, nwords, pct, mixed = mixed_stats(text)
        print(f"\n### {name}")
        print(f"    язык={info.language} p={info.language_probability:.2f} | "
              f"смешанных слов: {nmix}/{nwords} = {pct:.1f}%"
              + (f"  -> {mixed}" if mixed else ""))
        print(f"    {text}")
    print("\n" + "=" * 72)
    print("Меньше «смешанных слов» = лучше. Проверь, что бренды в тексте остались "
          "латиницей ЦЕЛИКОМ (это норма), а русские слова — чисто кириллицей.")


if __name__ == "__main__":
    main()
