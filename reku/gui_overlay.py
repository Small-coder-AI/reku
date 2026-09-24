"""Индикатор диктовки поверх всех окон — плашка внизу экрана.

Нажал хоткей — видно, что идёт запись (время и уровень звука), затем «Распознаю…»
и итог; через секунду плашка исчезает. Окно не берёт фокус и пропускает клики
насквозь: иначе текст вставился бы в саму плашку, а не туда, где стоял курсор.
Анимация идёт только пока плашка на экране.
"""
import math
import time
from collections import deque

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics, QCursor, QGuiApplication, QPen
from PySide6.QtWidgets import QWidget

from reku import gui_theme as T

_SHADOW = 10          # поле под мягкую тень вокруг плашки
_H = 40               # высота плашки
_PAD = 16             # внутренний отступ слева и справа
_BARS = 16            # столбиков мини-вэйвформа
_BAR_W, _BAR_GAP = 3.0, 2.0
_BOTTOM_GAP = 56      # от нижнего края рабочей области (над панелью задач)
_MAX_TEXT_W = 440     # шире — перенос; ошибка — до двух строк, дальше многоточие
_LINE_H = 18          # добавка к высоте плашки за вторую строку
_HOLD_MS = {"done": 1100, "empty": 1300, "error": 3500}

_TEXT = {"transcribing": "Распознаю…", "done": "Вставлено",
         "empty": "Ничего не распознано"}


class RecordingOverlay(QWidget):
    """Плашка-индикатор. Кормится теми же событиями, что и главное окно:
    on_state(state, detail), on_result(), set_level(rms)."""

    def __init__(self, cfg):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.cfg = cfg
        self.mode = None          # None | recording | transcribing | done | empty | error
        self._detail = ""
        self._t0 = 0.0
        self._got_result = False
        self._level = 0.0
        self._bars = deque([0.0] * _BARS, maxlen=_BARS)
        self._phase = 0.0
        self._anchor = None       # (центр x, низ y) плашки на экране — на весь цикл
        self._pill_h = _H

        self._font = QFont("Segoe UI")
        self._font.setPixelSize(13)
        self._font.setWeight(QFont.Weight.DemiBold)
        self._fm = QFontMetrics(self._font)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._on_tick)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.dismiss)

    # ── события движка ───────────────────────────────────────
    def on_state(self, state, detail=None):
        if state == "recording":
            if not self.cfg.show_overlay:
                return
            self._got_result = False
            self._t0 = time.monotonic()
            self._bars.extend([0.0] * _BARS)
            self._set_mode("recording")
        elif state == "transcribing":
            if self.mode == "recording":
                self._set_mode("transcribing")
        elif state == "idle":
            if self.mode in ("recording", "transcribing"):
                self._set_mode("done" if self._got_result else "empty")
        elif state == "error":
            # ошибка видна и без окна: микрофон не найден, запись прервалась,
            # модель не загрузилась при старте в трей
            if self.cfg.show_overlay:
                # переводы строк из текста исключений — в пробелы, иначе строки
                # налезают друг на друга в плашке
                self._detail = " ".join((detail or "Ошибка").split())
                self._set_mode("error")

    def on_result(self):
        self._got_result = True

    def set_level(self, rms):
        """Только запоминает уровень — перерисовку ведёт таймер."""
        self._level = min(1.0, rms * 14.0)

    def dismiss(self):
        self._tick.stop()
        self._hide_timer.stop()
        self.mode = None
        self._anchor = None
        self.hide()

    # ── внутреннее ───────────────────────────────────────────
    def text(self):
        if self.mode == "recording":
            s = int(time.monotonic() - self._t0)
            return f"Запись  {s // 60}:{s % 60:02d}"
        if self.mode == "error":
            return self._detail
        return _TEXT.get(self.mode, "")

    def lines(self):
        """Текст по строкам: ошибка переносится по словам (до двух строк) — её
        конец обычно самое важное («текст в буфере обмена (Ctrl+V)»)."""
        text = self.text()
        if self.mode != "error" or self._fm.horizontalAdvance(text) <= _MAX_TEXT_W:
            return [text]
        words, first = text.split(), ""
        while words and self._fm.horizontalAdvance((first + " " + words[0]).strip()) <= _MAX_TEXT_W:
            first = (first + " " + words.pop(0)).strip()
        if not first:                     # одно гигантское «слово» — просто обрезать
            return [self._fm.elidedText(text, Qt.ElideRight, _MAX_TEXT_W)]
        rest = self._fm.elidedText(" ".join(words), Qt.ElideRight, _MAX_TEXT_W)
        return [first, rest] if rest else [first]

    def _set_mode(self, mode):
        self.mode = mode
        self._hide_timer.stop()
        # ширина — по самому длинному тексту режима, чтобы плашка не дёргалась
        # от тиков секундомера
        lines = ["Запись  00:00"] if mode == "recording" else self.lines()
        w = _PAD + 10 + 10 + max(self._fm.horizontalAdvance(t) for t in lines) + _PAD
        if mode == "recording":
            w += 12 + _BARS * (_BAR_W + _BAR_GAP)
        self._pill_h = _H + _LINE_H * (len(lines) - 1)
        self.setFixedSize(int(w) + 2 * _SHADOW, self._pill_h + 2 * _SHADOW)
        self._place()
        if not self.isVisible():
            self.show()
        if mode in ("recording", "transcribing"):
            if not self._tick.isActive():
                self._tick.start(33)          # ~30 fps, только пока идёт запись/распознавание
        else:
            self._tick.stop()
            self._hide_timer.start(_HOLD_MS[mode])
        self.update()

    def _place(self):
        """Внизу по центру экрана, где сейчас курсор; в пределах одного цикла
        плашка стоит на месте и меняет только ширину."""
        if self._anchor is None:
            scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            if scr is None:
                return
            g = scr.availableGeometry()
            self._anchor = (g.center().x(), g.bottom() - _BOTTOM_GAP + _SHADOW)
        cx, bottom = self._anchor
        self.move(cx - self.width() // 2, bottom - self.height())

    def _on_tick(self):
        self._phase += 0.12
        if self.mode == "recording":
            self._bars.append(self._level)
        self.update()

    def hideEvent(self, e):
        self._tick.stop()
        super().hideEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pill = QRectF(_SHADOW, _SHADOW, self.width() - 2 * _SHADOW, self._pill_h)
        rad = _H / 2

        # мягкая тень: несколько полупрозрачных слоёв, чуть сдвинутых вниз
        p.setPen(Qt.NoPen)
        for i in range(1, 6):
            p.setBrush(QColor(0, 0, 0, 14))
            grow = i * 1.6
            p.drawRoundedRect(pill.adjusted(-grow, -grow + 2, grow, grow + 2),
                              rad + grow, rad + grow)

        card, border = T.RGB["card"], T.RGB["border"]
        p.setBrush(QColor(*card, 246))
        p.setPen(QPen(QColor(*border), 1))
        p.drawRoundedRect(pill, rad, rad)

        # значок состояния слева
        cx, cy = pill.left() + _PAD + 5, pill.center().y()
        pulse = 0.5 + 0.5 * abs(math.sin(self._phase))
        if self.mode == "done":
            pen = QPen(QColor(*T.RGB["ok"]), 2.2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPolyline([QPointF(cx - 5, cy), QPointF(cx - 1.5, cy + 3.5),
                            QPointF(cx + 5, cy - 4)])
        else:
            rgb = {"recording": T.RGB["rec"], "transcribing": T.RGB["busy"],
                   "error": T.RGB["rec"]}.get(self.mode, T.RGB["dim"])
            alpha = int(120 + 135 * pulse) if self.mode in ("recording", "transcribing") else 255
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(*rgb, alpha))
            p.drawEllipse(QPointF(cx, cy), 5, 5)

        # текст
        p.setFont(self._font)
        p.setPen(QColor(*T.RGB["text"]))
        tx = cx + 5 + 10
        text_rect = QRectF(tx, pill.top(), pill.right() - _PAD - tx, self._pill_h)
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, "\n".join(self.lines()))

        # мини-вэйвформ справа — только во время записи
        if self.mode == "recording":
            p.setPen(Qt.NoPen)
            x0 = pill.right() - _PAD - _BARS * (_BAR_W + _BAR_GAP) + _BAR_GAP
            max_h = _H - 18
            for i, lv in enumerate(self._bars):
                bh = max(3.0, lv * max_h)
                p.setBrush(QColor(*T.RGB["rec"], int(110 + 145 * lv)))
                p.drawRoundedRect(QRectF(x0 + i * (_BAR_W + _BAR_GAP), cy - bh / 2, _BAR_W, bh),
                                  _BAR_W / 2, _BAR_W / 2)
        p.end()
