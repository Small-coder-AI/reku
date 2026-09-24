"""Офскрин-тесты Фазы 0 по интерфейсу (без модели/GPU/мыши).
Запуск (из корня репозитория): python tests/test_gui_offscreen.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from reku import autostart
from reku import config
from reku import gui_theme as T
from reku.dictate import DictationApp
from reku.gui import Bridge, MainWindow, _should_start_minimized


def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    return cond


ok = True

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
# Дефолты, а не config.load(): load() создаёт config.json в настоящем каталоге данных
# (у dev-чекаута — корень репозитория), а чужие настройки (тема и т.п.) меняли бы ход теста.
cfg = config.Config()

bridge = Bridge()
engine = DictationApp(cfg, on_state=bridge.stateChanged.emit,
                      on_result=bridge.resultReady.emit,
                      on_level=bridge.levelChanged.emit)
win = MainWindow(cfg, engine=engine, bridge=bridge)
win.stack.setCurrentIndex(0)   # orb/wave живут на главной странице
win.show(); app.processEvents()

# ── 1. close/min: общий прозрачный стиль (#WinBtn), close — доп. role=close ──
tb = win.titlebar
ok &= check("mini использует #WinBtn", tb.mini_btn.objectName() == "WinBtn")
ok &= check("close использует ТОТ ЖЕ #WinBtn (не свой CloseBtn)",
            tb.close_btn.objectName() == "WinBtn")
ok &= check("close помечен role=close (красный hover через QSS)",
            tb.close_btn.property("role") == "close")
ok &= check("mini НЕ помечен role=close", tb.mini_btn.property("role") != "close")

# ── 2. ошибка: перенос строк, тултип с полным текстом, не «тихий» стиль ──
long_err = ("Звук с микрофона прерывался (1.3 c) — текст не вставлен, "
            "он в буфере обмена (Ctrl+V)")
engine._last_error = long_err
win.set_state("error"); app.processEvents()
ok &= check("hint: word wrap включён", win.hint.wordWrap())
ok &= check("hint: текст = полное сообщение (не обрезано)", win.hint.text() == long_err)
ok &= check("hint: тултип = полное сообщение", win.hint.toolTip() == long_err)
ok &= check("hint: текст можно выделить мышью",
            bool(win.hint.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse))
ok &= check("hint: включён стиль ошибки (errorState=true)",
            win.hint.property("errorState") == "true")
win_height_with_error = win.height()
ok &= check("окно не выросло из-за длинной ошибки", win_height_with_error == 640)

win.set_state("idle")
ok &= check("hint: после выхода из error тултип очищен", win.hint.toolTip() == "")
ok &= check("hint: после выхода из error стиль ошибки снят",
            win.hint.property("errorState") != "true")

# ── 3. QSizeGrip — ребёнок карточки, инсет внутрь от скруглённого угла ──
ok &= check("grip — ребёнок карточки (не окна)", win._grip.parent() is win.card)
card_rect = win.card.rect()            # локальные координаты card — grip в них же
grip_rect = win._grip.geometry()
ok &= check("grip целиком внутри границ карточки", card_rect.contains(grip_rect))

# ── 4. таймеры orb/wave: стоят, когда окно скрыто, снова идут после show ──
win.set_state("recording"); app.processEvents()
ok &= check("orb: таймер идёт (видно, идёт запись)", win.orb._timer.isActive())
ok &= check("wave: таймер идёт (видно, идёт запись)", win.wave._timer.isActive())

win.hide(); app.processEvents()
ok &= check("orb: таймер стоит, когда окно скрыто", not win.orb._timer.isActive())
ok &= check("wave: таймер стоит, когда окно скрыто", not win.wave._timer.isActive())

win.show(); app.processEvents()
ok &= check("orb: таймер снова идёт после show", win.orb._timer.isActive())
ok &= check("wave: таймер снова идёт после show", win.wave._timer.isActive())

win.set_state("loading")   # статичный pulse — анимировать нечего
ok &= check("orb: таймер стоит в 'loading' (нечего анимировать)",
            not win.orb._timer.isActive())

win.set_state("idle")      # запись кончилась, буфер вэйвформа пуст с самого начала
ok &= check("wave: таймер стоит в покое (не идёт запись, буфер пуст)",
            not win.wave._timer.isActive())

# ── 5. флаг --minimized: чистый хелпер + автозапуск ──
ok &= check("_should_start_minimized с флагом -> True",
            _should_start_minimized(["reku", "--minimized"]) is True)
ok &= check("_should_start_minimized без флага -> False",
            _should_start_minimized(["reku"]) is False)
ok &= check("autostart._exe_command() содержит --minimized",
            "--minimized" in autostart._exe_command())

# ── 6. иконки — рисованные (не шрифтовые), не пустые в обеих темах ──
for theme in ("dark", "light"):
    win.cfg.theme = theme
    win.apply_theme()
    icons = [tb.mini_btn.icon(), tb.close_btn.icon(), win.gear_btn.icon(), win.back_btn.icon()]
    ok &= check(f"{theme}: иконки mini/close/gear/back не пустые",
                all(not i.isNull() for i in icons))
T.set_active_theme(T.DARK)   # вернуть тёмную — не влиять на другие импорты в процессе

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
