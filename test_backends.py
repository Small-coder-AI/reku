"""Тесты бэкендов. Запуск: python test_backends.py (GPU не нужен)."""
import backends
from backends import resolve_runtime, select_backend, CTranslate2Backend, \
    OpenVINOBackend, ApiBackend
from types import SimpleNamespace as S


def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    return cond


ok = True

# resolve_runtime: auto + есть CUDA -> cuda/float16, модель не трогаем
ok &= check("auto+cuda -> cuda/float16/large-v3",
            resolve_runtime("auto", "auto", "large-v3", cuda_available=True)
            == ("cuda", "float16", "large-v3"))

# auto + нет CUDA + тяжёлая модель -> cpu/int8/small (понижение)
ok &= check("auto+no-cuda+heavy -> cpu/int8/small",
            resolve_runtime("auto", "auto", "large-v3", cuda_available=False)
            == ("cpu", "int8", "small"))

# auto + нет CUDA + лёгкая модель -> остаётся как есть
ok &= check("auto+no-cuda+light -> cpu/int8/base",
            resolve_runtime("auto", "auto", "base", cuda_available=False)
            == ("cpu", "int8", "base"))

# явный cpu НЕ понижает модель (это решение пользователя)
ok &= check("явный cpu не понижает модель",
            resolve_runtime("cpu", "auto", "large-v3", cuda_available=False)
            == ("cpu", "int8", "large-v3"))

# явный cuda + явный compute -> без изменений
ok &= check("явный cuda+float16",
            resolve_runtime("cuda", "float16", "medium", cuda_available=True)
            == ("cuda", "float16", "medium"))

# select_backend: device=api -> ApiBackend (заглушка), .load() кидает NotImplementedError
cfg_api = S(device="api", compute_type="auto", model="small")
b = select_backend(cfg_api)
ok &= check("api -> ApiBackend", isinstance(b, ApiBackend))
try:
    b.load()
    ok &= check("ApiBackend.load кидает NotImplementedError", False)
except NotImplementedError:
    ok &= check("ApiBackend.load кидает NotImplementedError", True)

# select_backend: локальный путь -> CTranslate2Backend с разрешённым устройством
cfg_loc = S(device="auto", compute_type="auto", model="large-v3")
b2 = select_backend(cfg_loc, cuda_probe=lambda: False)
ok &= check("auto+no-cuda -> CTranslate2Backend/cpu",
            isinstance(b2, CTranslate2Backend) and b2.device == "cpu"
            and b2.model_id == "small")
ok &= check("device_label для cpu", b2.device_label == "CPU")

# model_kind: CT2 -> "ct2" (вид модели для model_store.ensure_downloaded)
ok &= check("CTranslate2Backend.model_kind == ct2",
            CTranslate2Backend("small", "cpu", "int8").model_kind == "ct2")

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
