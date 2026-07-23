"""Лог старта: ярлык запускает pythonw, у которого нет stdout/stderr вовсе —
любая ошибка запуска (битый пакет в venv, DLL, конфиг) умирала молча, и для
пользователя это выглядело как «ничего не запускается» (боевой случай 2026-07:
null bytes в site-packages, диагностика — вечер переписки в Telegram).

init() зовётся ПЕРВОЙ строкой gui.py, до импорта PySide6 и pynput, чтобы
поймать и их падения. С консолью (dev-запуск python -m reku) не делает
ничего: логи и так видны."""
import os
import sys


def default_path():
    from reku import config
    return os.path.join(config.data_dir(), "reku.log")


def init(path=None):
    """Если консоли нет — перенаправить stdout/stderr в лог-файл и включить
    faulthandler (хард-краши в нативных DLL тоже попадают в лог). Прошлый лог
    сохраняется рядом как reku.log.1 (одна ротация — хватает для «пришли лог»).

    Возвращает путь к логу, либо None: есть консоль или лог занят. Занятый
    лог — это второй экземпляр при живом первом (single-instance): ротировать
    открытый файл Windows не даст, тогда просто живём без лога. Падать из-за
    логирования нельзя ни при каких условиях."""
    if sys.stdout is not None or sys.stderr is not None:
        return None
    try:
        path = path or default_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            os.replace(path, path + ".1")
        f = open(path, "w", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = f
        import faulthandler
        faulthandler.enable(file=f)
        return path
    except Exception:
        return None
