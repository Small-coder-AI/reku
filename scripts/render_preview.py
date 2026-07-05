"""Офскрин-рендер UI в PNG для самопроверки вида (без модели/движка).
Запуск (из корня репозитория): QT_QPA_PLATFORM=offscreen python scripts/render_preview.py"""
import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtCore import Qt

from reku import config
from reku.gui import MainWindow

app = QApplication([])
cfg = config.load()


def compose(win, name):
    win.show()
    app.processEvents()
    pm = win.grab()
    # на серый «десктоп», чтобы видеть скругление и прозрачные поля честно
    bg = QPixmap(pm.size()); bg.fill(QColor(43, 45, 49))
    p = QPainter(bg); p.drawPixmap(0, 0, pm); p.end()
    # было захардкожено на c:\Dev\whisper_ptt (чужой путь/диск) — чинил попутно,
    # раз уж трогал импорты в этом файле; см. отчёт по Task 5
    bg.save(os.path.join(ROOT, f"_preview_{name}.png"))
    print("saved", name)


win = MainWindow(cfg)

# idle + пример текста
win.set_state("idle")
win.orb._phase = 0.8
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
