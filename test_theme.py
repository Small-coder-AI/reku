"""Тесты темы (Фаза 3): мутация словарей на месте, build_qss, resolve_theme.
GPU/окно не нужны. Запуск: python test_theme.py"""
import gui_theme as T


def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    return cond


ok = True

# дефолт — тёмная; словари заполнены, есть состояние error
ok &= check("старт = тёмная", T.ACTIVE.name == "dark")
ok &= check("STATE_RGB содержит error", "error" in T.STATE_RGB)
ok &= check("RGB содержит accent", "accent" in T.RGB)

# мутация на месте: идентичность словарей сохраняется (это критично — gui_widgets
# держат ссылку на эти же объекты и читают их в paintEvent)
rgb_id, state_id = id(T.RGB), id(T.STATE_RGB)
dark_accent = T.RGB["accent"]
qss = T.set_active_theme(T.LIGHT)
ok &= check("RGB не пересоздан (мутация на месте)", id(T.RGB) == rgb_id)
ok &= check("STATE_RGB не пересоздан", id(T.STATE_RGB) == state_id)
ok &= check("после LIGHT accent поменялся", T.RGB["accent"] != dark_accent)
ok &= check("ACTIVE = light", T.ACTIVE.name == "light")
ok &= check("алиас ACCENT обновился", T.ACCENT == T.LIGHT.accent)

# build_qss отражает палитру
ok &= check("QSS светлой содержит светлый фон", T.LIGHT.bg_window.lower() in qss.lower())
ok &= check("QSS содержит #RowLabel", "#RowLabel" in qss)

# resolve_theme: прямой выбор и устойчивость 'system' без Qt-приложения
ok &= check("resolve_theme('dark') = DARK", T.resolve_theme("dark") is T.DARK)
ok &= check("resolve_theme('light') = LIGHT", T.resolve_theme("light") is T.LIGHT)
ok &= check("resolve_theme('system') не падает", T.resolve_theme("system") in (T.DARK, T.LIGHT))

T.set_active_theme(T.DARK)   # вернуть тёмную, чтобы не влиять на другие импорты

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
