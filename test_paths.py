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

# ── model_store: OV-модели (маркер + скачивание через snapshot_download) ──
_ov_id = "OpenVINO/whisper-large-v3-int8-ov"
_ov_dir = model_store.model_path(_ov_id)

# is_cached видит OV-маркер .download_complete
os.makedirs(_ov_dir, exist_ok=True)
open(os.path.join(_ov_dir, ".download_complete"), "w").close()
ok &= check("is_cached=True по OV-маркеру", model_store.is_cached(_ov_id) is True)

# is_cached видит model.bin (CT2, существующее поведение)
_ct2_dir = model_store.model_path("small")
os.makedirs(_ct2_dir, exist_ok=True)
open(os.path.join(_ct2_dir, "model.bin"), "w").close()
ok &= check("is_cached=True по model.bin", model_store.is_cached("small") is True)

# ensure_downloaded(kind="ov"): зовёт huggingface_hub.snapshot_download и пишет маркер
import huggingface_hub
_calls = []
_orig_sd = huggingface_hub.snapshot_download


def _fake_sd(repo, local_dir):
    _calls.append((repo, local_dir))
    os.makedirs(local_dir, exist_ok=True)


huggingface_hub.snapshot_download = _fake_sd
try:
    _new_id = "OpenVINO/whisper-large-v3-turbo-int8-ov"
    p = model_store.ensure_downloaded(_new_id, kind="ov")
    ok &= check("ensure_downloaded(ov) зовёт snapshot_download",
                bool(_calls) and _calls[0][0] == _new_id)
    ok &= check("ensure_downloaded(ov) пишет маркер",
                os.path.isfile(os.path.join(p, ".download_complete")))
    ok &= check("повторный вызов не качает снова (кэш)",
                model_store.ensure_downloaded(_new_id, kind="ov") == p
                and len(_calls) == 1)
finally:
    huggingface_hub.snapshot_download = _orig_sd

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
