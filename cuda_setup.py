"""Кладёт DLL из pip-пакетов nvidia-* в PATH. Импортируй ПЕРВЫМ — до faster_whisper.

Почему PATH, а не os.add_dll_directory: CTranslate2 грузит cublas64_12.dll /
cudnn*.dll через голый LoadLibrary, который ищет их только рядом с ctranslate2.dll,
в System32 и в PATH. Каталоги из add_dll_directory он НЕ видит (тот флаг чтит ctypes,
но не ct2). Без этого encode() на CUDA падает: 'cublas64_12.dll cannot be loaded'.
nvidia-cuda-runtime-cu12 (cudart) НЕ нужен — ct2 линкует его статически.

FROZEN-AWARE: в собранном .exe (PyInstaller --onedir) nvidia-DLL лежат в
<dist>/_internal/nvidia/<lib>/bin. nvidia — namespace-пакет (PEP420, без __init__.py),
поэтому importlib.util.find_spec("nvidia") во frozen НЕ находит его. Во frozen ищем
каталог nvidia/ напрямую относительно sys._MEIPASS и каталога .exe; из исходников —
через find_spec (по живому site-packages).
"""
import os
import sys
import importlib.util


def _frozen_nvidia_roots():
    """Каталоги, где во frozen лежат nvidia/*/bin. Сначала _MEIPASS (onedir =
    каталог _internal), затем каталог самого .exe — на оба случая раскладки."""
    roots = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(meipass)
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    roots.append(exe_dir)
    roots.append(os.path.join(exe_dir, "_internal"))
    return roots


def _nvidia_root():
    """Корень пакета nvidia (где лежат подпапки cublas/cudnn/cuda_nvrtc).
    Frozen: ищем nvidia/ рядом с .exe / в _internal. Иначе: через find_spec."""
    if getattr(sys, "frozen", False):
        for base in _frozen_nvidia_roots():
            cand = os.path.join(base, "nvidia")
            if os.path.isdir(cand):
                return cand
        return None
    spec = importlib.util.find_spec("nvidia")
    if not spec or not spec.submodule_search_locations:
        return None
    return spec.submodule_search_locations[0]


def add_cuda_dlls_to_path():
    """Возвращает список добавленных каталогов (для диагностики)."""
    root = _nvidia_root()
    if not root or not os.path.isdir(root):
        return []
    added = []
    for name in os.listdir(root):
        bindir = os.path.join(root, name, "bin")
        if os.path.isdir(bindir):
            os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]
            added.append(bindir)
    # во frozen ctranslate2.dll и его cudnn64_9.dll лежат в _internal —
    # добавим и эти каталоги, чтобы LoadLibrary точно их видел.
    if getattr(sys, "frozen", False):
        for base in _frozen_nvidia_roots():
            if os.path.isdir(base) and base not in os.environ["PATH"].split(os.pathsep):
                os.environ["PATH"] = base + os.pathsep + os.environ["PATH"]
                added.append(base)
    return added


# выполняется при импорте — поэтому импортировать модуль нужно до faster_whisper
_ADDED = add_cuda_dlls_to_path()
