"""Офскрин-тесты Фазы 0 по интерфейсу (без модели/GPU/мыши).
Запуск (из корня репозитория): python tests/test_gui_offscreen.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# шрифты Windows: без них offscreen берёт запасной шрифт вдвое шире Segoe UI,
# и проверки переноса текста в плашке меряют не то, что увидит пользователь
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QSizeGrip

from reku import autostart
from reku import config
from reku import gui_theme as T
from reku.dictate import DictationApp
from reku.gui import Bridge, MainWindow, DEFAULT_SIZE, _should_start_minimized
from reku.gui_resize import BAND_IN, edge_at


def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    return cond


def _center(widget, win):
    """Центр виджета в координатах окна."""
    p = widget.mapTo(win, widget.rect().center())
    return p.x(), p.y()


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
ok &= check("окно не выросло из-за длинной ошибки", win_height_with_error == DEFAULT_SIZE[1])

win.set_state("idle")
ok &= check("hint: после выхода из error тултип очищен", win.hint.toolTip() == "")
ok &= check("hint: после выхода из error стиль ошибки снят",
            win.hint.property("errorState") != "true")

# ── 3. растягивание за любой край/угол вместо уголка QSizeGrip ──
ok &= check("уголка QSizeGrip больше нет", not win.findChildren(QSizeGrip))
c = win.card.geometry()
L, Tp, R, B = c.left(), c.top(), c.right(), c.bottom()
mx, my = (L + R) // 2, (Tp + B) // 2
ok &= check("левый край", edge_at(L + 1, my, L, Tp, R, B) == (-1, 0))
ok &= check("правый край (в поле тени)", edge_at(R + 5, my, L, Tp, R, B) == (1, 0))
ok &= check("верх", edge_at(mx, Tp - 3, L, Tp, R, B) == (0, -1))
ok &= check("низ", edge_at(mx, B, L, Tp, R, B) == (0, 1))
ok &= check("угол: у края, но рядом с углом — диагональ",
            edge_at(R - 1, B - 12, L, Tp, R, B) == (1, 1))
ok &= check("левый верхний угол", edge_at(L + 10, Tp + 1, L, Tp, R, B) == (-1, -1))
ok &= check("середина карточки — не край", edge_at(mx, my, L, Tp, R, B) == (0, 0))
ok &= check("далеко в поле тени — не край", edge_at(L - 12, my, L, Tp, R, B) == (0, 0))
ok &= check("кнопка ✕ в заголовке не в зоне края",
            edge_at(*_center(win.titlebar.close_btn, win), L, Tp, R, B) == (0, 0))

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

# ── 7. плашка-индикатор записи поверх окон ──
ov = win.overlay
win.set_state("idle"); ov.dismiss(); app.processEvents()
flags = ov.windowFlags()
ok &= check("плашка не берёт фокус (текст уйдёт в нужное окно)",
            bool(flags & Qt.WindowDoesNotAcceptFocus)
            and ov.testAttribute(Qt.WA_ShowWithoutActivating))
ok &= check("плашка пропускает клики", bool(flags & Qt.WindowTransparentForInput))
ok &= check("плашка поверх окон и без кнопки в панели задач",
            bool(flags & Qt.WindowStaysOnTopHint) and bool(flags & Qt.Tool))
ok &= check("в покое плашки нет", not ov.isVisible())

bridge.stateChanged.emit("recording"); app.processEvents()
ok &= check("хоткей нажат -> плашка «Запись»",
            ov.isVisible() and ov.mode == "recording" and ov.text().startswith("Запись"))
ok &= check("во время записи анимация идёт", ov._tick.isActive())
bridge.levelChanged.emit(0.05); app.processEvents()
ok &= check("уровень звука доходит до плашки", ov._level > 0)
bridge.stateChanged.emit("transcribing"); app.processEvents()
ok &= check("отпустил -> «Распознаю…»", ov.mode == "transcribing" and ov.text() == "Распознаю…")
bridge.resultReady.emit("текст"); bridge.stateChanged.emit("idle"); app.processEvents()
ok &= check("вставлено -> «Вставлено» и скоро исчезнет",
            ov.mode == "done" and ov._hide_timer.isActive() and not ov._tick.isActive())
ov.dismiss(); app.processEvents()
ok &= check("после паузы плашка скрыта", not ov.isVisible() and ov.mode is None)

bridge.stateChanged.emit("recording"); bridge.stateChanged.emit("transcribing")
bridge.stateChanged.emit("idle"); app.processEvents()
ok &= check("пустая диктовка -> «Ничего не распознано»", ov.mode == "empty")
ov.dismiss()

engine._last_error = "Микрофон не найден"
bridge.stateChanged.emit("error"); app.processEvents()
ok &= check("ошибка видна на плашке", ov.mode == "error" and ov.text() == "Микрофон не найден")
ov.dismiss()

engine._last_error = long_err
bridge.stateChanged.emit("error"); app.processEvents()
ok &= check("длинная ошибка переносится, конец («Ctrl+V») не теряется",
            1 < len(ov.lines()) <= 2 and "Ctrl+V" in ov.lines()[-1])
ok &= check("плашка под две строки выше однострочной",
            ov.height() > 40 + 2 * 10)
ov.dismiss()
engine._last_error = "строка 1\nстрока 2\n\tстрока 3"
bridge.stateChanged.emit("error"); app.processEvents()
ok &= check("переводы строк из текста ошибки схлопнуты", "\n" not in ov.text())
ov.dismiss(); win.set_state("idle")

cfg.show_overlay = False
bridge.stateChanged.emit("recording"); app.processEvents()
ok &= check("индикатор выключен в настройках -> плашки нет", not ov.isVisible())
bridge.stateChanged.emit("idle"); app.processEvents()
cfg.show_overlay = True

# ── 8. настройки: «Применить» всегда видна, колесо не меняет значения ──
inner = win.settings_scroll.widget()
ok &= check("«Применить» вне прокрутки",
            not inner.isAncestorOf(win.apply_btn))
ok &= check("редкие настройки свёрнуты в «Дополнительно»",
            not win.adv_btn.isChecked() and win.adv_box.isHidden()
            and win.adv_box.isAncestorOf(win.prompt_edit))
win.adv_btn.setChecked(True)
ok &= check("«Дополнительно» раскрывается", not win.adv_box.isHidden())
win.adv_btn.setChecked(False)

win.stack.setCurrentIndex(1); app.processEvents()
sb_right = win.settings_scroll.mapTo(win.card, win.settings_scroll.rect().topRight()).x()
ok &= check("полоса прокрутки настроек не под зоной захвата края",
            sb_right < win.card.width() - 1 - BAND_IN)
combo = win.model_combo
before = combo.currentIndex()
wheel = QWheelEvent(QPointF(5, 5), QPointF(combo.mapToGlobal(QPoint(5, 5))), QPoint(0, 0),
                    QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
QApplication.sendEvent(combo, wheel)
ok &= check("колесо над комбобоксом без фокуса не меняет модель",
            combo.currentIndex() == before)
win.stack.setCurrentIndex(0)

# ── 9. смена модели во время записи: перезагрузка — после записи, окно не врёт ──
import threading
reloaded = threading.Event()
win._reload_with_rollback = lambda old: reloaded.set()   # без настоящей загрузки модели
bridge.stateChanged.emit("recording"); app.processEvents()
win._start_reload(("large-v3", "auto", "auto"))
ok &= check("во время записи перезагрузка отложена, окно остаётся в «Записи»",
            win._pending_reload is not None and win._state == "recording"
            and ov.mode == "recording")
bridge.stateChanged.emit("transcribing"); bridge.stateChanged.emit("idle")
app.processEvents(); app.processEvents()
ok &= check("после записи отложенная перезагрузка запущена",
            reloaded.wait(2) and win._pending_reload is None)
ov.dismiss()

print("\nИТОГ:", "ВСЕ ПРОШЛИ" if ok else "ЕСТЬ ПАДЕНИЯ")
raise SystemExit(0 if ok else 1)
