"""Тесты лога старта (reku/startlog.py) и порядка импортов gui.py.
Запуск (из корня репозитория): python tests/test_startup_log.py (GPU не нужен)."""
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    return cond


ok = True

from reku import startlog

# ── с консолью init() не делает ничего ───────────────────────
ok &= check("с консолью -> None (stdout/stderr не трогаем)",
            startlog.init() is None
            and sys.stdout is not None and sys.stderr is not None)

# ── без консоли: перенаправление в файл + ротация ────────────
_tmp = tempfile.mkdtemp(prefix="reku_startlog_")
_log = os.path.join(_tmp, "sub", "reku.log")   # каталога sub нет — init должен создать

_saved_out, _saved_err = sys.stdout, sys.stderr
try:
    sys.stdout = None
    sys.stderr = None
    _ret = startlog.init(path=_log)
    _f = sys.stdout
    print("привет из лога", flush=True)
    _err_ok = sys.stderr is _f                  # stderr и stdout — один файл
finally:
    import faulthandler
    faulthandler.disable()                      # иначе держит fd закрываемого файла
    if sys.stdout is not None and sys.stdout is not _saved_out:
        sys.stdout.close()
    sys.stdout, sys.stderr = _saved_out, _saved_err

ok &= check("без консоли -> возвращает путь", _ret == _log)
ok &= check("stderr перенаправлен туда же", _err_ok)
with open(_log, encoding="utf-8") as fh:
    ok &= check("print попал в лог", "привет из лога" in fh.read())

# повторный init (следующий запуск) ротирует прошлый лог в .1
_saved_out, _saved_err = sys.stdout, sys.stderr
try:
    sys.stdout = None
    sys.stderr = None
    startlog.init(path=_log)
finally:
    import faulthandler
    faulthandler.disable()
    if sys.stdout is not None and sys.stdout is not _saved_out:
        sys.stdout.close()
    sys.stdout, sys.stderr = _saved_out, _saved_err

with open(_log + ".1", encoding="utf-8") as fh:
    ok &= check("прошлый лог сохранён как .1", "привет из лога" in fh.read())
ok &= check("новый лог пуст/пересоздан", os.path.getsize(_log) == 0)

# ── ранняя диагностика (print до открытия файла) попадает в лог ──
# config.data_dir() при первом запуске печатает сообщения миграции каталога ещё
# ДО того, как лог открыт — init должен ловить их в буфер и переносить в файл
_tmp2 = tempfile.mkdtemp(prefix="reku_startlog2_")
_log2 = os.path.join(_tmp2, "reku.log")
_orig_dp = startlog.default_path


def _fake_dp():
    print("[config] ранняя диагностика миграции")
    return _log2


startlog.default_path = _fake_dp
_saved_out, _saved_err = sys.stdout, sys.stderr
try:
    sys.stdout = None
    sys.stderr = None
    _ret2 = startlog.init()             # path не задан -> зовётся default_path
finally:
    import faulthandler
    faulthandler.disable()
    if sys.stdout is not None and sys.stdout is not _saved_out:
        sys.stdout.close()
    sys.stdout, sys.stderr = _saved_out, _saved_err
    startlog.default_path = _orig_dp

with open(_log2, encoding="utf-8") as fh:
    ok &= check("ранний print из default_path попал в лог",
                _ret2 == _log2 and "ранняя диагностика миграции" in fh.read())

# ── сбой init: потоки восстановлены в None, а не брошены на вечный буфер ──
_saved_out, _saved_err = sys.stdout, sys.stderr
try:
    sys.stdout = None
    sys.stderr = None
    # родитель пути — ФАЙЛ (_log2), makedirs упадёт -> init должен вернуть None
    _ret3 = startlog.init(path=os.path.join(_log2, "x", "y.log"))
    _restored = (_ret3 is None and sys.stdout is None and sys.stderr is None)
finally:
    sys.stdout, sys.stderr = _saved_out, _saved_err
ok &= check("сбой init -> None, потоки снова None (не буфер)", _restored)

# ── порядок импортов в gui.py (защита от «уборки») ───────────
# 1) startlog.init — раньше всего: pythonw без него нем, краши импортов
#    PySide6/pynput иначе снова станут невидимыми;
# 2) pynput — строго ДО PySide6: обход краша six+shiboken на Python 3.12.0.
with open(os.path.join(_ROOT, "reku", "gui.py"), encoding="utf-8") as fh:
    _src = fh.read()
_i_log = _src.find("startlog")
_i_pyn = _src.find("import pynput")
_i_qt = _src.find("from PySide6")
ok &= check("gui.py: startlog раньше pynput", 0 <= _i_log < _i_pyn)
ok &= check("gui.py: pynput раньше PySide6", 0 <= _i_pyn < _i_qt)

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
