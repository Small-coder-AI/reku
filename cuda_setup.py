"""Кладёт DLL из pip-пакетов nvidia-* в PATH. Импортируй ПЕРВЫМ — до faster_whisper.

Почему PATH, а не os.add_dll_directory: CTranslate2 грузит cublas64_12.dll /
cudnn*.dll через голый LoadLibrary, который ищет их только рядом с ctranslate2.dll,
в System32 и в PATH. Каталоги из add_dll_directory он НЕ видит (тот флаг чтит ctypes,
но не ct2). Без этого encode() на CUDA падает: 'cublas64_12.dll cannot be loaded'.
nvidia-cuda-runtime-cu12 (cudart) НЕ нужен — ct2 линкует его статически.
"""
import os
import importlib.util


def add_cuda_dlls_to_path():
    """Возвращает список добавленных каталогов (для диагностики)."""
    spec = importlib.util.find_spec("nvidia")
    if not spec or not spec.submodule_search_locations:
        return []
    root = spec.submodule_search_locations[0]
    added = []
    for name in os.listdir(root):
        bindir = os.path.join(root, name, "bin")
        if os.path.isdir(bindir):
            os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]
            added.append(bindir)
    return added


# выполняется при импорте — поэтому импортировать модуль нужно до faster_whisper
_ADDED = add_cuda_dlls_to_path()
