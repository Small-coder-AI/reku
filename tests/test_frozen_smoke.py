r"""Смоук-тест собранного .exe: проверяет, что GPU реально работает,
а не молча сфолбэчился на CPU из-за непойманной CUDA-DLL.

Запуск ПОСЛЕ build.ps1 (из корня репозитория):
    .venv\Scripts\python.exe tests\test_frozen_smoke.py

Что делает: запускает dist\Reku\Reku.exe с переменной
REKU_SELFTEST=1 — в этом режиме gui.main() НЕ поднимает UI, а
выполняет короткую самопроверку и пишет результат в %APPDATA%\Reku\
selftest.json, затем выходит. Тест читает json и проверяет device == 'cuda'.

ВНИМАНИЕ: чтобы это работало, в gui.main() в начале нужен хук self-test
(см. фрагмент в плане). Без хука тест запустит обычный GUI — тогда проверяй
вручную по подсказке в окне ('GPU (CUDA)' против 'CPU (GPU не найден)').
"""
import os
import sys
import json
import time
import subprocess

# tests/ теперь на один уровень глубже репозитория — dist/ живёт в корне
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "dist", "Reku", "Reku.exe")
RESULT = os.path.join(os.environ.get("APPDATA", ""), "Reku", "selftest.json")


def main():
    assert os.path.exists(EXE), f"нет .exe: {EXE} — сначала build.ps1"
    if os.path.exists(RESULT):
        os.remove(RESULT)

    env = dict(os.environ, REKU_SELFTEST="1")
    print("Запускаю self-test .exe (грузит модель, может занять ~10-30 c)...")
    p = subprocess.run([EXE], env=env, timeout=300)
    print(f"exit code: {p.returncode}")

    assert os.path.exists(RESULT), (
        "selftest.json не создан — либо нет хука self-test в gui.main(), "
        "либо .exe упал до записи результата")
    with open(RESULT, encoding="utf-8") as f:
        data = json.load(f)
    print("self-test:", json.dumps(data, ensure_ascii=False))

    assert data.get("cuda_device_count", 0) > 0, "ct2 не видит CUDA-устройств (DLL не пойманы!)"
    assert data.get("device") == "cuda", f"модель НЕ на GPU: device={data.get('device')!r} (CPU-фолбэк)"
    assert data.get("transcribe_ok"), "тестовая транскрипция не отработала"
    print("OK: GPU работает во frozen-сборке.")


if __name__ == "__main__":
    main()
