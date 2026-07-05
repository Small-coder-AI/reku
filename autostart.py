"""Автозапуск при старте Windows через HKCU\\...\\Run.

Пишем путь к .exe из sys.executable (во frozen это сам whisper_ptt.exe;
из исходников — python.exe, что для автозапуска dev-режима бессмысленно,
поэтому из исходников функция всё равно работает, но указывает на интерпретатор).
HKCU не требует прав администратора. Значение берём в кавычки на случай
пробелов в пути.
"""
import sys
import os

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "whisper_ptt"


def _exe_command() -> str:
    """Команда запуска для реестра. Frozen -> сам .exe. Иначе -> pythonw gui.py."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # dev-режим: запускаем gui.py через pythonw из текущего venv
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui.py")
    exe = pyw if os.path.exists(pyw) else sys.executable
    return f'"{exe}" "{script}"'


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
    (по умолчанию из _exe_command(): сам .exe во frozen, иначе pythonw gui.py)."""
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
