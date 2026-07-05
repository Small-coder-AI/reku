# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec для whisper_ptt: --onedir --windowed, вход gui.py.

Главный риск — CUDA-DLL: ct2 грузит cublas64_12.dll/cudnn*.dll голым
LoadLibrary, который смотрит только рядом с ctranslate2.dll, в System32 и в
PATH. Поэтому nvidia-DLL из pip-пакетов кладём в _internal/nvidia/<lib>/bin
(сохраняя структуру), а cuda_setup.py во frozen добавляет эти каталоги в PATH
ДО импорта faster_whisper. Структуру nvidia/ обязательно сохраняем — иначе
find_spec("nvidia") во frozen ничего не найдёт.

Сборка:  .venv\Scripts\pyinstaller.exe whisper_ptt.spec --noconfirm
"""
import os
from PyInstaller.utils.hooks import (
    collect_all, collect_dynamic_libs, collect_data_files, collect_submodules,
)

datas = []
binaries = []
hiddenimports = []

# ── ctranslate2: .pyd, ctranslate2.dll, cudnn64_9.dll, libiomp5md.dll ──
d, b, h = collect_all("ctranslate2")
datas += d; binaries += b; hiddenimports += h

# ── faster_whisper: ассеты (assets/*.bin для VAD-модели silero!) ──
d, b, h = collect_all("faster_whisper")
datas += d; binaries += b; hiddenimports += h

# ── nvidia-DLL: cublas/cudnn/cuda_nvrtc — кладём в nvidia/<lib>/bin ──
# collect_dynamic_libs сохраняет относительный путь внутри пакета, поэтому
# DLL ложатся как nvidia/cublas/bin/cublas64_12.dll и т.п. (это и нужно
# cuda_setup.py: он сканирует nvidia/*/bin). cuda_runtime НЕ нужен — ct2
# линкует cudart статически.
for pkg in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_nvrtc"):
    binaries += collect_dynamic_libs(pkg)
# ВАЖНО: nvidia — namespace-пакет PEP420, у него и подпакетов НЕТ __init__.py,
# поэтому find_spec("nvidia") во frozen НЕ сработает. cuda_setup.py во frozen
# это знает и сканирует каталог nvidia/<lib>/bin напрямую (не через find_spec).
# Заголовки (include/*.h) во frozen не нужны — НЕ собираем их (лишний вес).

# ── av (PyAV): свои FFmpeg-DLL ──
d, b, h = collect_all("av")
datas += d; binaries += b; hiddenimports += h

# ── onnxruntime: provider-DLL грузятся динамически ──
d, b, h = collect_all("onnxruntime")
datas += d; binaries += b; hiddenimports += h

# ── sounddevice: одиночный модуль (не пакет). PortAudio DLL лежит в
# _sounddevice_data/portaudio-binaries и грузится cffi относительно этой папки,
# поэтому собираем её как data (сохраняя путь _sounddevice_data/...). ──
datas += collect_data_files("_sounddevice_data")
hiddenimports += ["sounddevice", "_sounddevice", "_cffi_backend", "cffi"]

# ── pynput: бэкенды выбираются по платформе через importlib ──
hiddenimports += collect_submodules("pynput")

# ── прочее, что иногда не подхватывается анализом ──
hiddenimports += ["pyperclip", "numpy"]

# наши собственные модули (вход gui.py тянет dictate->backends->cuda_setup и т.д.)
hiddenimports += [
    "cuda_setup", "config", "dictate", "backends", "model_store",
    "postprocess", "gui_theme", "gui_widgets",
]

# ── иконка (генерируется build.ps1 из make_icon перед сборкой) ──
icon_path = "app.ico" if os.path.exists("app.ico") else None

a = Analysis(
    ["gui.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # уменьшаем вес: тяжёлые ненужные пакеты, которые могут затянуться
        "tkinter", "matplotlib", "scipy", "pandas", "PIL",
        "pytest", "IPython", "notebook", "torch", "torchaudio",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtMultimedia", "PySide6.Qt3DCore", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtQuick3D",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,        # --onedir: бинарники в COLLECT
    name="whisper_ptt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                    # UPX ломает nvidia/Qt-DLL — НЕ включать
    console=False,                # --windowed: без консоли (pythonw-эквивалент)
    disable_windowed_traceback=False,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="whisper_ptt",
)
