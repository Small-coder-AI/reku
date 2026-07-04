"""whisper_ptt — локальная диктовка по push-to-talk (голос → текст в активное окно).

Запуск:  python dictate.py
Настройки — в config.json (создаётся при первом запуске). См. config.py.

Импорт-безопасен: при импорте модуля приложение НЕ запускается (это делает трей).
"""
import sys

# Мгновенный фидбек при старте (под pythonw stdout=None — поэтому guard).
if sys.stdout:
    print("whisper_ptt: запускаюсь, гружу зависимости…", flush=True)

import cuda_setup  # noqa: F401 — кладёт nvidia DLL в PATH, СТРОГО до faster_whisper

import time
import threading

import numpy as np
import sounddevice as sd
import pyperclip
from pynput import keyboard
from pynput.keyboard import Key, Controller, KeyCode

import config
import postprocess

# Инференс инкапсулирован в backends.py (faster_whisper грузится лениво там,
# строго после cuda_setup). DictationApp работает через self.backend.


def parse_hotkey(name: str):
    """Имя из конфига -> объект pynput. 'ctrl_r' -> Key.ctrl_r; 'a' -> KeyCode('a')."""
    name = (name or "").strip()
    if hasattr(Key, name):
        return getattr(Key, name)
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    raise ValueError(f"неизвестный хоткей в config.json: {name!r} "
                     f"(ожидается имя Key.<...> или один символ)")


class DictationApp:
    """Ядро: запись -> распознавание -> вставка. UI (консоль/трей) цепляется
    через колбэки on_state(state) и on_result(text)."""

    STATES = ("loading", "downloading", "idle", "recording", "transcribing")

    def __init__(self, cfg: config.Config, on_state=None, on_result=None, on_level=None):
        self.cfg = cfg
        self.hotkey = parse_hotkey(cfg.hotkey)
        self.kb = Controller()
        self.backend = None

        self._recording = False
        self._transcribing = False
        self._key_held = False          # для toggle: реагировать раз на физическое нажатие
        self._frames = []
        self._stream = None
        self._lock = threading.Lock()
        self._listener = None

        self.on_state = on_state or self._print_state
        self.on_result = on_result or (lambda text: print(f"→ {text}\n", flush=True))
        self.on_level = on_level or (lambda rms: None)   # живой уровень звука для UI

    # ── статус по умолчанию (консоль) ────────────────────────
    @staticmethod
    def _print_state(state):
        msg = {"loading": "Загружаю модель (первый запуск ~5-10 c, не прерывай)...",
               "idle": None,
               "recording": "● запись...",
               "transcribing": "⏳ распознаю..."}.get(state)
        if msg:
            print(msg, flush=True)

    def _set_state(self, state):
        try:
            self.on_state(state)
        except Exception as e:  # колбэк UI не должен ронять ядро
            print(f"[on_state] {e}", file=sys.stderr)

    # ── загрузка модели ──────────────────────────────────────
    def load_model(self):
        import backends
        self.backend = backends.select_backend(self.cfg)
        try:
            self._download_and_load()
        except Exception as e:
            # Спека Фазы 2, «Обработка ошибок»: сбой OpenVINO в auto-режиме
            # (драйвер/память/компиляция) -> тихий откат на CPU, приложение живо.
            if not (self.cfg.device == "auto"
                    and isinstance(self.backend, backends.OpenVINOBackend)):
                raise
            print(f"[fallback] OpenVINO не поднялся ({e}); перехожу на CPU",
                  file=sys.stderr, flush=True)
            self.backend = backends.cpu_fallback_backend(self.cfg)
            self._download_and_load()

    def _download_and_load(self):
        import model_store
        mid = self.backend.model_id
        if mid and not model_store.is_cached(mid):
            self._set_state("downloading")
            model_store.ensure_downloaded(
                mid, kind=self.backend.model_kind,
                on_progress=lambda m: print(
                    f"Скачиваю модель '{m}' (первый запуск, может занять минуты)…",
                    flush=True))
        self._set_state("loading")
        t0 = time.perf_counter()
        self.backend.load()
        print(f"Модель '{mid or self.backend.name}' на {self.backend.device_label} "
              f"за {time.perf_counter() - t0:.1f} c.", flush=True)
        self._set_state("idle")

    # ── запись ───────────────────────────────────────────────
    def start_rec(self):
        with self._lock:
            if self._recording or self._transcribing:
                return
            self._recording = True
            self._frames = []

        def cb(indata, n, t, status):
            if self._recording:
                self._frames.append(indata.copy())
                rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
                self.on_level(rms)

        self._stream = sd.InputStream(samplerate=self.cfg.sample_rate, channels=1,
                                      dtype="float32", callback=cb)
        self._stream.start()
        self._set_state("recording")

    def stop_and_transcribe(self):
        with self._lock:
            if not self._recording:
                return
            self._recording = False
            self._transcribing = True
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
                self._stream = None
            if not self._frames:
                return
            audio = np.concatenate(self._frames, axis=0).flatten()
            self._set_state("transcribing")
            text = self.transcribe(audio)
            if text:
                self.insert(text)
                self.on_result(text)
            else:
                print("(пусто)\n", flush=True)
        finally:
            self._transcribing = False
            self._set_state("idle")

    # ── распознавание + фильтр ───────────────────────────────
    def transcribe(self, audio: np.ndarray) -> str:
        c = self.cfg
        t0 = time.perf_counter()
        segments, info = self.backend.transcribe(audio, c)
        # вторичный страж: на не-речи language_probability валится (~0.2)
        if c.min_language_probability and info.language_probability < c.min_language_probability:
            print(f"[filter] подавлено: lang={info.language} "
                  f"p={info.language_probability:.2f} < {c.min_language_probability}", flush=True)
            return ""
        texts = postprocess.clean_segments(
            segments,
            drop_hallucinations=c.drop_hallucinations,
            max_compression_ratio=c.max_compression_ratio,
        )
        text = postprocess.join_text(texts)
        dt = time.perf_counter() - t0
        print(f"[{dt:.2f}s, lang={info.language} p={info.language_probability:.2f}]",
              flush=True)
        return text

    # ── вставка в активное окно ──────────────────────────────
    def insert(self, text: str):
        if self.cfg.trailing_space:
            text = text + " "
        if self.cfg.insert_method == "type":
            self.kb.type(text)
            return
        # paste: через буфер обмена + Ctrl+V
        old = None
        if self.cfg.restore_clipboard:
            try:
                old = pyperclip.paste()
            except Exception:
                old = None
        pyperclip.copy(text)
        time.sleep(0.1)
        # Ctrl+V по ФИЗИЧЕСКОМУ коду клавиши V (0x56), а не по символу 'v':
        # press('v') зависит от активной раскладки — при русской раскладке символ
        # уходит как Unicode-ввод и НЕ комбинируется с Ctrl, поэтому вставка не
        # срабатывает (диагностика diag_paste.py: способ с 'v' падал, с VK — работал).
        # Микро-задержки между модификатором и клавишей — чтобы окно успело увидеть Ctrl.
        v_key = KeyCode.from_vk(0x56)
        self.kb.press(Key.ctrl); time.sleep(0.03)
        self.kb.press(v_key); time.sleep(0.03)
        self.kb.release(v_key); time.sleep(0.03)
        self.kb.release(Key.ctrl)
        time.sleep(0.1)
        if old is not None:
            try:
                pyperclip.copy(old)
            except Exception:
                pass

    # ── хоткей ───────────────────────────────────────────────
    def _matches(self, key) -> bool:
        if isinstance(self.hotkey, Key):
            return key == self.hotkey
        return getattr(key, "char", None) == getattr(self.hotkey, "char", object())

    def _on_press(self, key):
        if not self._matches(key):
            return
        if self.cfg.mode == "toggle":
            if self._key_held:           # подавляем авто-повтор удержания
                return
            self._key_held = True
            if self._recording:
                threading.Thread(target=self.stop_and_transcribe, daemon=True).start()
            else:
                self.start_rec()
        else:  # ptt
            self.start_rec()

    def _on_release(self, key):
        if not self._matches(key):
            return
        if self.cfg.mode == "toggle":
            self._key_held = False
        else:  # ptt
            threading.Thread(target=self.stop_and_transcribe, daemon=True).start()

    def start(self):
        """Грузит модель (если ещё нет) и запускает слушатель клавиш. Не блокирует."""
        if self.backend is None:
            self.load_model()
        mode_hint = ("нажми хоткей — старт, нажми снова — стоп"
                     if self.cfg.mode == "toggle" else "держи хоткей и говори")
        print(f"Готово. Режим: {self.cfg.mode} ({self.cfg.hotkey}). "
              f"{mode_hint}. Ctrl+C — выход.\n", flush=True)
        self._listener = keyboard.Listener(on_press=self._on_press,
                                            on_release=self._on_release)
        self._listener.start()

    def run(self):
        """Консольный запуск: стартует и блокируется до выхода."""
        self.start()
        self._listener.join()

    def stop(self):
        if self._listener is not None:
            self._listener.stop()

    def apply_config(self):
        """Перечитать настройки, влияющие на live-поведение (хоткей). Режим/язык
        читаются в обработчиках на каждое нажатие, их перечитывать не нужно."""
        try:
            self.hotkey = parse_hotkey(self.cfg.hotkey)
        except ValueError as e:
            print(f"[apply_config] {e}", file=sys.stderr)

    def reload_model(self):
        """Перезагрузка модели (после смены model/device/compute). Зови в фоне."""
        with self._lock:
            if self._recording or self._transcribing:
                return False
            self.backend = None
        self.load_model()
        return True


def main():
    cfg = config.load()
    app = DictationApp(cfg)
    try:
        app.run()
    except KeyboardInterrupt:
        print("\nВыход.")
        sys.exit(0)


if __name__ == "__main__":
    main()
