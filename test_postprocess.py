"""Тесты пост-фильтра. Запуск: python test_postprocess.py (GPU не нужен)."""
from types import SimpleNamespace as S
from postprocess import normalize, is_hallucination_phrase, clean_segments, join_text


def seg(text, cr=1.0):
    return S(text=text, compression_ratio=cr)


def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    return cond


ok = True

# normalize
ok &= check("normalize пунктуация/регистр", normalize("  Спасибо, ЗА просмотр!! ") == "спасибо за просмотр")

# блок-лист фантомов
ok &= check("en фантом", is_hallucination_phrase("Thank you for watching!"))
ok &= check("ru фантом", is_hallucination_phrase("Продолжение следует..."))
ok &= check("пустой = фантом", is_hallucination_phrase("   "))
ok &= check("реальная речь не фантом", not is_hallucination_phrase("открой настройки Claude Code"))

# clean_segments: фантом вырезается, реальный текст остаётся
r = clean_segments([seg("Thank you for watching!"), seg("привет мир")])
ok &= check("вырезал фантом, оставил речь", r == ["привет мир"])

# дедуп подряд идущих повторов
r = clean_segments([seg("да да да"), seg("да да да"), seg("дальше")])
ok &= check("дедуп подряд-повторов", r == ["да да да", "дальше"])

# порог compression_ratio режет «пересжатые» (повторяющиеся) сегменты
r = clean_segments([seg("нормальный текст", cr=1.5), seg("а а а а а а а а", cr=3.0)])
ok &= check("режет высокий compression_ratio", r == ["нормальный текст"])

# не-подряд повтор НЕ режется (легитимное повторение через другой сегмент)
r = clean_segments([seg("раз"), seg("два"), seg("раз")])
ok &= check("не-подряд повтор сохраняется", r == ["раз", "два", "раз"])

# join
ok &= check("join_text", join_text(["а", "б"]) == "а б")

# можно отключить блок-лист
r = clean_segments([seg("Thank you")], drop_hallucinations=False)
ok &= check("блок-лист отключаем", r == ["Thank you"])

# H1-фикс: короткие/общеупотребимые реплики БОЛЬШЕ не режутся блок-листом
ok &= check("'you' не фантом (короткая речь)", not is_hallucination_phrase("you"))
ok &= check("'bye' не фантом", not is_hallucination_phrase("bye"))
ok &= check("'thank you' не фантом", not is_hallucination_phrase("thank you"))
ok &= check("'субтитры' не фантом", not is_hallucination_phrase("субтитры"))
ok &= check("'добро пожаловать' не фантом", not is_hallucination_phrase("добро пожаловать"))
ok &= check("clean_segments сохраняет короткое 'you'",
            clean_segments([seg("you"), seg("привет")]) == ["you", "привет"])
# но многословные титры-сигнатуры всё ещё режутся
ok &= check("'спасибо за просмотр' фантом", is_hallucination_phrase("Спасибо за просмотр"))
ok &= check("'субтитры подготовлены сообществом' фантом",
            is_hallucination_phrase("Субтитры подготовлены сообществом"))

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
