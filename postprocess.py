"""Пост-фильтр галлюцинаций Whisper. Чистые функции — тестируются без GPU.

Слои защиты (по убыванию надёжности, см. диагностику diag_halluc.py):
  1. VAD (в transcribe) — режет не-речь в ноль. Главная защита, не здесь.
  2. Декодер: condition_on_previous_text=False + no_repeat_ngram_size — меньше петель.
  3. Здесь: блок-лист фирменных фантомов + дедуп повторов + порог compression_ratio.
  4. Опционально (в вызывающем коде): порог info.language_probability.
"""
import re

# Фирменные фантомы Whisper на не-речи (мультиязычно). В нижнем регистре, без пунктуации.
# Диагностика показала: large-v3 на тишине/шуме упорно выдаёт "Thank you for watching".
#
# ВАЖНО (фикс «слова-исключения работают черти как»): сюда попадают ТОЛЬКО
# многословные титры-сигнатуры, которые не спутать с короткой реальной речью.
# Раньше тут были одиночные "you", "bye", "thank you", "субтитры", "добро
# пожаловать", "спасибо за внимание" — is_hallucination_phrase резал ВЕСЬ сегмент
# при точном совпадении, поэтому короткие легитимные реплики молча пропадали.
HALLUCINATION_PHRASES = {
    # en — многословные титры YouTube
    "thank you for watching", "thanks for watching", "thank you for watching!",
    "please subscribe", "like and subscribe", "subscribe to my channel",
    "see you next time",
    # ru — служебные титры/подписи, типичные для Whisper на тишине
    "продолжение следует", "продолжение следует...", "спасибо за просмотр",
    "субтитры подготовлены сообществом", "редактор субтитров",
    "субтитры создавал", "субтитры сделал", "субтитры делал",
    "продолжение в следующей серии", "до новых встреч",
}

_punct_re = re.compile(r"[^\w\s]", re.UNICODE)
_space_re = re.compile(r"\s+")


def normalize(text: str) -> str:
    """нижний регистр, без пунктуации, схлопнутые пробелы — для сравнения."""
    t = _punct_re.sub("", text.lower())
    return _space_re.sub(" ", t).strip()


def is_hallucination_phrase(text: str) -> bool:
    n = normalize(text)
    if not n:
        return True
    return n in HALLUCINATION_PHRASES


def clean_segments(
    segments,
    *,
    drop_hallucinations: bool = True,
    max_compression_ratio: float = 2.4,
) -> list[str]:
    """segments — итерируемое объектов с .text и (опц.) .compression_ratio.
    Возвращает список текстов сегментов: без фантомов, без подряд-повторов,
    без «пересжатых» (повторяющихся) сегментов. Порядок сохраняется.
    """
    out: list[str] = []
    prev_norm = None
    for s in segments:
        text = (getattr(s, "text", "") or "").strip()
        if not text:
            continue
        if drop_hallucinations and is_hallucination_phrase(text):
            continue
        cr = getattr(s, "compression_ratio", 0.0) or 0.0
        if max_compression_ratio and cr > max_compression_ratio:
            continue
        n = normalize(text)
        if n and n == prev_norm:        # дедуп подряд идущих одинаковых сегментов
            continue
        prev_norm = n
        out.append(text)
    return out


def join_text(texts: list[str]) -> str:
    return " ".join(texts).strip()
