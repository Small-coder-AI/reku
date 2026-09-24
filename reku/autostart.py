"""Автозапуск при старте Windows через HKCU\\...\\Run.

Пишем путь к .exe из sys.executable (во frozen это сам Reku.exe;
из исходников — python.exe, что для автозапуска dev-режима бессмысленно,
поэтому из исходников функция всё равно работает, но указывает на интерпретатор).
HKCU не требует прав администратора. Значение берём в кавычки на случай
пробелов в пути.
"""
import sys
import os

from reku import APP_NAME

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = APP_NAME   # имя значения в реестре = имя продукта (единая константа)


def _exe_command() -> str:
    """Команда запуска для реестра. Frozen -> сам .exe. Иначе -> pythonw -m reku.
    Всегда с --minimized: автозапуск не должен разворачивать окно при каждом
    входе в Windows, только поднимать трей.

    dev-режим: реестр (HKCU\\...\\Run) стартует процесс с произвольным рабочим
    каталогом (не обязательно корень репо), поэтому просто "-m reku" ненадёжен —
    пакет reku резолвится, только если его родитель есть в sys.path. Вместо
    этого явно подставляем ROOT (родитель reku/, вычисленный от __file__) через
    -c, это не зависит от cwd процесса автозапуска. --minimized добавлен ПОСЛЕ
    закрывающей кавычки -c "код" — это отдельный аргумент командной строки,
    Python кладёт его в sys.argv[1:] (argv[0] при -c это сама строка "-c")."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    # dev-режим: запускаем через pythonw из текущего venv
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    exe = pyw if os.path.exists(pyw) else sys.executable
    code = f"import sys; sys.path.insert(0, r'{root}'); from reku.gui import main; main()"
    return f'"{exe}" -c "{code}" --minimized'


def is_enabled() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            val, _ = winreg.QueryValueEx(k, _VALUE_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_enabled(enabled: bool, command: str | None = None) -> None:
    """Включить/выключить автозапуск. Идемпотентно. command — явная строка запуска
    (по умолчанию из _exe_command(): сам .exe во frozen, иначе pythonw -m reku)."""
    import winreg
    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            winreg.SetValueEx(k, _VALUE_NAME, 0, winreg.REG_SZ, command or _exe_command())
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, _VALUE_NAME)
        except FileNotFoundError:
            pass


def ensure_minimized_flag() -> None:
    """Дописать --minimized в уже сохранённую в реестре команду автозапуска, если
    его там ещё нет: миграция для установок, включивших автозапуск до появления
    этого флага — иначе они и дальше разворачивали бы окно при каждом входе."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            command, _ = winreg.QueryValueEx(k, _VALUE_NAME)
    except OSError:
        return   # автозапуск выключен или ключа ещё нет — нечего мигрировать
    if not command or "--minimized" in command:
        return
    set_enabled(True, command=command + " --minimized")
