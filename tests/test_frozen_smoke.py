r"""Смоук-тест собранного .exe: проверяет, что GPU реально работает,
а не молча сфолбэчился на CPU из-за непойманной DLL.

Запуск ПОСЛЕ build.ps1 (из корня репозитория):
    .venv\Scripts\python.exe tests\test_frozen_smoke.py

Какой стек проверять — переменная REKU_SMOKE_DEVICE (по умолчанию cuda):
    cuda — NVIDIA-профиль: ct2 видит CUDA, модель на device='cuda';
    igpu — Intel-профиль (OpenVINO): модель на device='igpu' — ловит
           недособранный OV-рантайм (плагины девайсов/openvino_tokenizers.dll
           PyInstaller без collect_all не тащит — ревью PR #3).
В %APPDATA%\Reku\config.json при этом должен стоять тот же device
(селфтест грузит модель по обычному конфигу). Чтобы не трогать боевой
конфиг, можно подменить APPDATA на песочный каталог — тест и .exe
смотрят в одну и ту же переменную окружения.

Что делает: запускает dist\Reku\Reku.exe с переменной
REKU_SELFTEST=1 — в этом режиме gui.main() НЕ поднимает UI, а
выполняет короткую самопроверку и пишет результат в %APPDATA%\Reku\
selftest.json, затем выходит. Тест читает json и сверяет device.

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
TARGET = os.environ.get("REKU_SMOKE_DEVICE", "cuda")   # cuda | igpu


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

    if TARGET == "cuda":
        assert data.get("cuda_device_count", 0) > 0, "ct2 не видит CUDA-устройств (DLL не пойманы!)"
    assert data.get("device") == TARGET, (
        f"модель НЕ на {TARGET}: device={data.get('device')!r} "
        f"(фолбэк или недособранный рантайм; error={data.get('error')!r})")
    assert data.get("transcribe_ok"), "тестовая транскрипция не отработала"
    print(f"OK: {TARGET} работает во frozen-сборке.")


if __name__ == "__main__":
    main()
