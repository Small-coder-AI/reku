"""Тесты надёжности (Фаза 1): сбой загрузки -> состояние 'error', целостность
кэша модели, guard None language_probability. GPU не нужен.
Запуск: python test_robustness.py"""
import os
import tempfile
from types import SimpleNamespace as S

import numpy as np

import config


def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    return cond


ok = True

# ── 1. load_model: сбой backend.load() -> состояние 'error', backend=None ──
import backends
from dictate import DictationApp

states = []


class FailingBackend:
    name = "fake"; model_id = None; device_label = "CPU"; device = "cpu"
    def load(self):
        raise RuntimeError("симулированный сбой загрузки")
    def transcribe(self, audio, cfg):
        raise AssertionError("не должно вызываться")


_orig_select = backends.select_backend
backends.select_backend = lambda cfg: FailingBackend()
app = DictationApp(config.Config(), on_state=lambda s: states.append(s))
try:
    app.load_model()
    raised = False
except RuntimeError:
    raised = True
backends.select_backend = _orig_select

ok &= check("load_model пробрасывает исключение", raised)
ok &= check("последнее состояние = 'error'", bool(states) and states[-1] == "error")
ok &= check("backend обнулён после сбоя", app.backend is None)
ok &= check("_last_error заполнен", bool(app._last_error))

# ── 2. is_cached: полный набор vs оборванная докачка ──
import model_store

_tmp = tempfile.mkdtemp()
config.data_dir = lambda: _tmp        # монкипатч источника правды путей


def _touch(d, *names):
    os.makedirs(d, exist_ok=True)
    for n in names:
        open(os.path.join(d, n), "w").close()


_touch(model_store.model_path("full-model"), "model.bin", "config.json", "tokenizer.json")
ok &= check("полный набор -> is_cached True", model_store.is_cached("full-model") is True)

_touch(model_store.model_path("partial-model"), "model.bin")   # только bin
ok &= check("только model.bin -> is_cached False", model_store.is_cached("partial-model") is False)

_touch(model_store.model_path("notok-model"), "model.bin", "config.json")   # нет токенайзера
ok &= check("нет токенайзера -> is_cached False", model_store.is_cached("notok-model") is False)

# ── 3. transcribe: None language_probability не роняет (guard M4) ──
class NoLangProbBackend:
    name = "fake"; model_id = None; device_label = "CPU"; device = "cpu"
    def load(self): pass
    def transcribe(self, audio, cfg):
        return iter([S(text="привет", compression_ratio=1.0)]), \
            S(language="ru", language_probability=None)


app2 = DictationApp(config.Config(min_language_probability=0.5))
app2.backend = NoLangProbBackend()
try:
    out = app2.transcribe(np.zeros(16000, dtype=np.float32))
    crashed = False
except TypeError:
    crashed, out = True, None
ok &= check("None language_probability не роняет transcribe", not crashed)
ok &= check("текст прошёл (страж не сработал на None)", out == "привет")

# ── 4. миграция конфига: старый латинский промпт -> русский якорь + hotwords ──
import json
_cfg_path = os.path.join(tempfile.mkdtemp(), "config.json")
with open(_cfg_path, "w", encoding="utf-8") as f:
    json.dump({"initial_prompt": config._LEGACY_INITIAL_PROMPT, "hotwords": ""}, f)
migrated = config.load(_cfg_path)
ok &= check("миграция: initial_prompt стал русским якорем",
            migrated.initial_prompt == config.Config.initial_prompt)
ok &= check("миграция: бренды переехали в hotwords",
            migrated.hotwords == config._LEGACY_INITIAL_PROMPT)

# кастомный промпт пользователя НЕ трогаем
with open(_cfg_path, "w", encoding="utf-8") as f:
    json.dump({"initial_prompt": "мой свой промпт", "hotwords": "OData"}, f)
keep = config.load(_cfg_path)
ok &= check("кастомный промпт не перезаписан", keep.initial_prompt == "мой свой промпт")
ok &= check("кастомные hotwords не тронуты", keep.hotwords == "OData")

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
