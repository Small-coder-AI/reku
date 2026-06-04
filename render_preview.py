"""Офскрин-рендер UI в PNG для самопроверки вида (без модели/движка).
Запуск: QT_QPA_PLATFORM=offscreen python render_preview.py"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtCore import Qt

import config
from gui import MainWindow

app = QApplication([])
cfg = config.load()


def compose(win, name):
    win.show()
    app.processEvents()
    pm = win.grab()
    # на серый «десктоп», чтобы видеть скругление и прозрачные поля честно
    bg = QPixmap(pm.size()); bg.fill(QColor(43, 45, 49))
    p = QPainter(bg); p.drawPixmap(0, 0, pm); p.end()
    bg.save(rf"c:\Dev\whisper_ptt\_preview_{name}.png")
    print("saved", name)


win = MainWindow(cfg)

# idle + пример текста
win.set_state("idle")
win.orb._phase = 0.8
win.text.setPlainText("открой настройки Claude Code и запусти Passivbot")
compose(win, "idle")

# recording — выставим уровень и вэйвформ вручную (без event loop)
win.set_state("recording")
win.orb._level = 0.72; win.orb._phase = 1.2
import math
win.wave._active = True
win.wave._buf.clear()
for i in range(win.wave._n):
    win.wave._buf.append(0.2 + 0.6 * abs(math.sin(i * 0.5)))
compose(win, "recording")

# transcribing
win.set_state("transcribing")
win.orb._phase = 0.6
compose(win, "transcribing")

# settings page
win.stack.setCurrentIndex(1)
compose(win, "settings")

print("done")
