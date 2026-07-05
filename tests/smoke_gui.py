"""Headless-проверка проводки UI (без модели/VRAM). offscreen.
Запуск (из корня репозитория): python tests/smoke_gui.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from reku import config
from reku.dictate import DictationApp
from reku.gui import MainWindow, Bridge, make_icon
from reku import gui_theme as T

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
cfg = config.load()

bridge = Bridge()
engine = DictationApp(cfg, on_state=bridge.stateChanged.emit,
                      on_result=bridge.resultReady.emit,
                      on_level=bridge.levelChanged.emit)
win = MainWindow(cfg, engine=engine, bridge=bridge)
_ = make_icon(T.STATE_RGB["idle"])          # рисование иконки трея
print("tray available:", QSystemTrayIcon.isSystemTrayAvailable())

win.show(); app.processEvents()

assert win.runtime_lbl.text().startswith("Работает:")

# гоняем состояния через сигналы (имитация колбэков из рабочих потоков)
for s in ["loading", "idle", "recording", "transcribing", "idle"]:
    bridge.stateChanged.emit(s); app.processEvents()
bridge.levelChanged.emit(0.5); app.processEvents()
bridge.resultReady.emit("тестовый распознанный текст"); app.processEvents()

# текст больше не дублируется в UI — показывается подтверждение «вставлено»
assert win._flashing and win.status.text() == "✓ вставлено"

# настройки: применить без смены модели (не должно триггерить reload)
win.stack.setCurrentIndex(1); app.processEvents()
win._apply_settings(); app.processEvents()

assert win._state == "idle"
print("hotkey parsed:", engine.hotkey)
print("SMOKE OK: вся проводка без исключений, модель не грузилась")
