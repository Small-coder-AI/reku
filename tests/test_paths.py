"""Тесты путей. Запуск (из корня репозитория): python tests/test_paths.py (GPU не нужен)."""
import os
import sys
import tempfile
import contextlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    return cond


@contextlib.contextmanager
def frozen_appdata(path):
    """Подменяет sys.frozen=True и %APPDATA% на время блока. Нужно потому, что
    data_dir() во frozen-режиме теперь мигрирует старый каталог данных (побочный
    эффект) — без подмены APPDATA тест рисковал бы тронуть настоящий каталог
    пользователя, а не временный."""
    old_appdata = os.environ.get("APPDATA")
    os.environ["APPDATA"] = path
    sys.frozen = True
    try:
        yield
    finally:
        del sys.frozen
        if old_appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = old_appdata


ok = True

from reku import config

# data_dir() из исходников == корень репозитория (родитель пакета reku/), а НЕ
# каталог config.py — иначе в dev-режиме config.json/models/ ищутся не там, где
# реально лежат (баг переезда config.py в reku/ в Task 5: см. корневой config.json
# и models/ с уже скачанными моделями против пустых reku/config.json, reku/models/).
expected_src = os.path.dirname(os.path.dirname(os.path.abspath(config.__file__)))
ok &= check("data_dir из исходников = корень репо", config.data_dir() == expected_src)

# data_dir() во frozen-режиме = %APPDATA%\Reku (APPDATA подменён на temp-каталог)
with tempfile.TemporaryDirectory() as _appdata:
    with frozen_appdata(_appdata):
        d = config.data_dir()
    ok &= check("data_dir frozen = %APPDATA%\\Reku", d == os.path.join(_appdata, "Reku"))

# миграция: старый %APPDATA%/whisper_ptt переименовывается в %APPDATA%/Reku
# (модели ~3 ГБ внутри не перекачиваются повторно)
with tempfile.TemporaryDirectory() as _appdata:
    _old = os.path.join(_appdata, "whisper_ptt")
    os.makedirs(_old)
    with open(os.path.join(_old, "config.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    with frozen_appdata(_appdata):
        d = config.data_dir()
    _new = os.path.join(_appdata, "Reku")
    ok &= check("data_dir мигрирует whisper_ptt -> Reku", d == _new)
    ok &= check("миграция переносит config.json внутри",
                os.path.isfile(os.path.join(_new, "config.json")))
    ok &= check("миграция убирает старый каталог", not os.path.exists(_old))

# если новый каталог уже есть — старый не трогаем (не перезатираем данные)
with tempfile.TemporaryDirectory() as _appdata:
    _old = os.path.join(_appdata, "whisper_ptt")
    _new = os.path.join(_appdata, "Reku")
    os.makedirs(_old)
    os.makedirs(_new)
    with frozen_appdata(_appdata):
        d = config.data_dir()
    ok &= check("data_dir с уже существующим Reku = Reku (без миграции)", d == _new)
    ok &= check("старый whisper_ptt остаётся нетронутым", os.path.exists(_old))

# новые дефолты конфига
c = config.Config()
ok &= check("device дефолт = auto", c.device == "auto")
ok &= check("compute_type дефолт = auto", c.compute_type == "auto")
ok &= check("api поля присутствуют",
            hasattr(c, "api_provider") and hasattr(c, "api_base_url")
            and hasattr(c, "api_key") and hasattr(c, "api_model"))

# model_store: пути считаются от config.data_dir() (монкипатчим на temp)
from reku import model_store

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

# is_cached требует ПОЛНЫЙ набор CT2-файлов (Task 1 мерджа ужесточил проверку:
# model.bin+config.json+токенайзер, а не один model.bin — иначе оборванная
# докачка считалась бы «готова», см. model_store._dir_complete)
_ct2_dir = model_store.model_path("small")
os.makedirs(_ct2_dir, exist_ok=True)
open(os.path.join(_ct2_dir, "model.bin"), "w").close()
ok &= check("is_cached=False пока нет config.json/токенайзера (оборванная докачка)",
            model_store.is_cached("small") is False)
open(os.path.join(_ct2_dir, "config.json"), "w").close()
open(os.path.join(_ct2_dir, "tokenizer.json"), "w").close()
ok &= check("is_cached=True когда каталог полон (model.bin+config.json+токенайзер)",
            model_store.is_cached("small") is True)

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
