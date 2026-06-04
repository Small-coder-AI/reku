"""Тесты путей. Запуск: python test_paths.py (GPU не нужен)."""
import os
import sys


def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    return cond


ok = True

import config

# data_dir() из исходников == каталог config.py
expected_src = os.path.dirname(os.path.abspath(config.__file__))
ok &= check("data_dir из исходников = каталог скрипта", config.data_dir() == expected_src)

# data_dir() во frozen-режиме = %APPDATA%\whisper_ptt
sys.frozen = True
try:
    d = config.data_dir()
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    ok &= check("data_dir frozen = %APPDATA%\\whisper_ptt",
                d == os.path.join(appdata, "whisper_ptt"))
finally:
    del sys.frozen

# новые дефолты конфига
c = config.Config()
ok &= check("device дефолт = auto", c.device == "auto")
ok &= check("compute_type дефолт = auto", c.compute_type == "auto")
ok &= check("api поля присутствуют",
            hasattr(c, "api_provider") and hasattr(c, "api_base_url")
            and hasattr(c, "api_key") and hasattr(c, "api_model"))

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
