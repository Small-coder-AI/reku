"""Тесты config.py: сохранение/загрузка, атомарность save(), дефолты.
Запуск (из корня репозитория): python tests/test_config.py"""
import json
import os
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reku import config


def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    return cond


ok = True

# ── дефолты ──────────────────────────────────────────────────────
ok &= check("ov_num_beams по умолчанию 1", config.Config().ov_num_beams == 1)

_tmp = tempfile.mkdtemp(prefix="reku_cfg_test_")

# ── save/load: полный круг ──────────────────────────────────────
_path = os.path.join(_tmp, "config.json")
_cfg = config.Config()
_cfg.model = "medium"
_cfg.hotwords = "PostgreSQL, Redis"
_cfg.ov_num_beams = 3
config.save(_cfg, _path)
_loaded = config.load(_path)
ok &= check("roundtrip: model", _loaded.model == "medium")
ok &= check("roundtrip: hotwords", _loaded.hotwords == "PostgreSQL, Redis")
ok &= check("roundtrip: ov_num_beams", _loaded.ov_num_beams == 3)

# ── неизвестные ключи в файле молча игнорируются ─────────────────
_path_unknown = os.path.join(_tmp, "config_unknown.json")
with open(_path_unknown, "w", encoding="utf-8") as f:
    json.dump({"model": "small", "some_future_field": "xyz", "another_unknown": 42}, f)
_loaded_u = config.load(_path_unknown)
ok &= check("неизвестные ключи не роняют load()", _loaded_u.model == "small")
ok &= check("неизвестный ключ не осел атрибутом Config",
            not hasattr(_loaded_u, "some_future_field"))

# ── save() атомарен: сбой посередине не портит существующий файл ─
_path_atomic = os.path.join(_tmp, "config_atomic.json")
_good_cfg = config.Config()
_good_cfg.model = "large-v3"
config.save(_good_cfg, _path_atomic)
with open(_path_atomic, "rb") as f:
    _before = f.read()


def _boom_dump(obj, fp, **kw):
    fp.write('{"model": "por')   # частичная запись — как при обрыве посреди json.dump
    raise RuntimeError("симулированный сбой записи")


_orig_dump = json.dump
json.dump = _boom_dump
try:
    try:
        config.save(_good_cfg, _path_atomic)
        ok &= check("save() пробрасывает исключение при сбое записи", False)
    except RuntimeError:
        ok &= check("save() пробрасывает исключение при сбое записи", True)
finally:
    json.dump = _orig_dump

with open(_path_atomic, "rb") as f:
    _after = f.read()
ok &= check("файл не тронут при сбое записи (байт-в-байт)", _before == _after)
ok &= check("временных файлов не осталось",
            set(os.listdir(_tmp)) == {"config.json", "config_unknown.json",
                                      "config_atomic.json"})

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
