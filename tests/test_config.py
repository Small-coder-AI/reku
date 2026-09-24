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

_tmp = tempfile.mkdtemp(prefix="reku_cfg_test_")

# ── save/load: полный круг ──────────────────────────────────────
_path = os.path.join(_tmp, "config.json")
_cfg = config.Config()
_cfg.model = "medium"
_cfg.hotwords = "PostgreSQL, Redis"
_cfg.language = "en"
config.save(_cfg, _path)
_loaded = config.load(_path)
ok &= check("roundtrip: model", _loaded.model == "medium")
ok &= check("roundtrip: hotwords", _loaded.hotwords == "PostgreSQL, Redis")
ok &= check("roundtrip: language", _loaded.language == "en")

# ── неизвестные ключи в файле молча игнорируются ─────────────────
_path_unknown = os.path.join(_tmp, "config_unknown.json")
with open(_path_unknown, "w", encoding="utf-8") as f:
    # ov_num_beams — удалённое поле (beam search на OV-GPU падал): старый ключ безвреден
    json.dump({"model": "small", "some_future_field": "xyz", "ov_num_beams": 5}, f)
_loaded_u = config.load(_path_unknown)
ok &= check("неизвестные ключи не роняют load()", _loaded_u.model == "small")
ok &= check("неизвестный ключ не осел атрибутом Config",
            not hasattr(_loaded_u, "some_future_field"))
ok &= check("удалённое поле ov_num_beams не осело атрибутом Config",
            not hasattr(_loaded_u, "ov_num_beams"))

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

# битый файл: обычная загрузка берёт дефолты, strict — бросает (UI тогда не затирает
# файл дефолтами); JSON не-объект больше не роняет загрузку
for name, content in (("config_broken.json", '{"model": "tiny",'),
                      ("config_list.json", "[1, 2]")):
    _p = os.path.join(_tmp, name)
    with open(_p, "w", encoding="utf-8") as f:
        f.write(content)
    ok &= check(f"{name}: load() не падает и берёт дефолты",
                config.load(_p).model == config.Config().model)
    try:
        config.load(_p, strict=True)
        ok &= check(f"{name}: load(strict=True) бросает ValueError", False)
    except ValueError:
        ok &= check(f"{name}: load(strict=True) бросает ValueError", True)
    with open(_p, encoding="utf-8") as f:
        ok &= check(f"{name}: сам файл не тронут", f.read() == content)

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
