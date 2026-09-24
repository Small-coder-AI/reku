"""Пост-фильтр галлюцинаций Whisper. Чистые функции — тестируются без GPU.

Слои защиты (по убыванию надёжности, см. диагностику diag_halluc.py):
  1. VAD (в transcribe) — режет не-речь в ноль. Главная защита, не здесь.
  2. Декодер: condition_on_previous_text=False + temperature fallback самого
     faster-whisper (перекодирует окно при compression_ratio > 2.4) — меньше петель.
  3. Здесь: блок-лист фирменных фантомов, срез подписей титровальщиков в хвосте,
     дедуп повторов, порог compression_ratio.
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

# Подписи титровальщиков: Whisper выучил их на YouTube-субтитрах и дописывает на
# тишине в конце записи — «…и всё. Субтитры создавал <ник>». Точное совпадение фразы
# их не ловит (после подписи идёт ник, перед ней — реальная речь), поэтому режем
# хвостом: от подписи до конца текста. Подпись — ключевые слова, а за ними ТОЛЬКО
# имена в титровом виде: ник латиницей или инициалы с фамилией. «Субтитры сделали
# отвратительно» и «субтитры сделай крупнее» — речь, их не трогаем.
_LATIN = r"[A-Za-z][\w.\-]*"                    # ник или сайт: NickName, Amara.org
_INITIALS = r"[А-ЯЁA-Z]\.\s?[А-ЯЁA-Z][\w\-]*"    # А.Иванов, A. Smith
_NAME = rf"(?:{_INITIALS}|{_LATIN})"
_NAMES = rf"{_NAME}(?:[\s,]+{_NAME}){{0,3}}"
_VERB = (r"(?:создавал|создала|создали|сделал|сделала|сделали|сделаны|делал|делала"
         r"|делали|подготовил|подготовила|подготовили|подготовлены|предоставил"
         r"|предоставила|предоставлены|редактировал|редактировала|перевёл|перевел|перевела)")
# ключевые слова без учёта регистра, имена — с учётом (заглавная — признак имени)
_CREDIT_RE = re.compile(
    r"(?:"
    rf"(?i:субтитр\w*)(?:\s*:|\s+(?i:{_VERB})(?:\s+(?i:сообществом))?)\s+{_NAMES}"
    rf"|(?i:редактор\s+субтитров)\s+{_INITIALS}(?:\s+(?i:корректор)\s+{_INITIALS})?"
    rf"|(?i:корректор)\s+{_INITIALS}"
    rf"|(?i:subtitles\s+by)\s+(?:(?i:the)\s+)?{_NAMES}(?:\s+(?i:community))?"
    r"|(?i:amara\.org)"
    r")[\s.!…]*")
_CREDIT_START = re.compile(r"(?i)(?<!\w)(?:субтитр|редактор|корректор|subtitles|amara\.org)")


def _credit_tail_start(text: str):
    """Позиция, с которой начинается хвост-подпись, или None."""
    for m in _CREDIT_START.finditer(text):
        i = m.start()
        if not _CREDIT_RE.fullmatch(text, i):
            continue
        before = text[:i].rstrip()
        # подпись — отдельное «предложение»: начало текста или после .!?…; без точки —
        # только если Whisper начал её с заглавной («…сделал Субтитры создавал …»).
        # Голый сайт посреди фразы («зайди на сайт Amara.org») — речь.
        if not before or before[-1] in ".!?…»\"":
            return i
        if text[i].isupper() and not text[i:].lower().startswith("amara"):
            return i
    return None


def strip_credit_tail(text: str) -> str:
    """Срезать с конца текста подписи титровальщиков (их бывает несколько подряд)."""
    while (i := _credit_tail_start(text)) is not None:
        text = text[:i].rstrip()
    return text


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
        if drop_hallucinations:
            text = strip_credit_tail(text)
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
