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

# model_store: пути считаются от config.data_dir() (монкипатчим на temp)
import tempfile
import model_store

_tmp = tempfile.mkdtemp()
config.data_dir = lambda: _tmp  # монкипатч источника правды путей
ok &= check("model_cache_dir = data_dir/models",
            model_store.model_cache_dir() == os.path.join(_tmp, "models"))
ok &= check("model_path безопасит '/'",
            model_store.model_path("Systran/faster-whisper-small")
            == os.path.join(_tmp, "models", "Systran_faster-whisper-small"))
ok &= check("is_cached=False для несуществующей",
            model_store.is_cached("small") is False)

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
