"""Кастомные рисованные виджеты: MicOrb (анимированный) и WaveformStrip."""
import math
from collections import deque

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import (QPainter, QColor, QRadialGradient, QPen, QBrush,
                           QPainterPath, QConicalGradient)
from PySide6.QtWidgets import QWidget

import gui_theme as T


def _c(rgb, a=255):
    return QColor(rgb[0], rgb[1], rgb[2], a)


class MicOrb(QWidget):
    """Светящийся орб с микрофоном. Дышит (idle), пульсирует по уровню (rec),
    крутит дугу (transcribing). Анимация — таймер ~60 fps, поэтому корректно
    рендерится и офскрин (фазу можно выставить вручную перед grab)."""

    def __init__(self, parent=None, size=168):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._state = "idle"
        self._level = 0.0       # сглаженный уровень 0..1
        self._phase = 0.0       # фаза анимации
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def set_state(self, state):
        self._state = state
        self.update()

    def set_level(self, rms):
        target = min(1.0, rms * 14.0)
        # атака быстрая, спад плавный
        if target > self._level:
            self._level += (target - self._level) * 0.5
        else:
            self._level += (target - self._level) * 0.15
        self.update()

    def _tick(self):
        self._phase += 0.045
        if self._state != "recording":
            self._level *= 0.85   # затухание, когда не пишем
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width(); h = self.height()
        cx, cy = w / 2, h / 2
        rgb = T.STATE_RGB.get(self._state, T.RGB["accent"])

        # пульсация радиуса
        if self._state == "recording":
            pulse = 0.06 + 0.5 * self._level
        elif self._state == "idle":
            pulse = 0.04 + 0.03 * math.sin(self._phase * 1.6)   # дыхание
        elif self._state == "transcribing":
            pulse = 0.05 + 0.02 * math.sin(self._phase * 4)
        else:
            pulse = 0.03
        base_r = min(w, h) * 0.27
        r = base_r * (1 + pulse)

        # внешнее свечение (радиус ≤ половины виджета — иначе градиент
        # обрезается квадратом по границе виджета)
        glow_r = min(w, h) * 0.5
        grad = QRadialGradient(cx, cy, glow_r)
        grad.setColorAt(0.0, _c(rgb, 130))
        grad.setColorAt(r / glow_r * 0.92, _c(rgb, 70))
        grad.setColorAt(1.0, _c(rgb, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(QPointF(cx, cy), glow_r, glow_r)

        # кольцо уровня (запись)
        if self._state == "recording" and self._level > 0.01:
            ring_r = min(r * (1.25 + 0.5 * self._level), glow_r * 0.99)
            pen = QPen(_c(rgb, int(90 + 120 * self._level)))
            pen.setWidthF(2.5)
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), ring_r, ring_r)

        # вращающаяся дуга (распознавание)
        if self._state == "transcribing":
            arc_r = r * 1.45
            rect = QRectF(cx - arc_r, cy - arc_r, arc_r * 2, arc_r * 2)
            pen = QPen(_c(rgb, 220)); pen.setWidthF(3.0); pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            start = int((-self._phase * 180 / math.pi) % 360) * 16
            p.drawArc(rect, start, 100 * 16)

        # тело орба (вертикальный градиент)
        body = QRadialGradient(cx, cy - r * 0.3, r * 1.4)
        body.setColorAt(0.0, _c(tuple(min(255, x + 40) for x in rgb), 255))
        body.setColorAt(1.0, _c(rgb, 255))
        p.setPen(Qt.NoPen); p.setBrush(QBrush(body))
        p.drawEllipse(QPointF(cx, cy), r, r)

        # микрофон (белый глиф)
        self._draw_mic(p, cx, cy, r)
        p.end()

    def _draw_mic(self, p, cx, cy, r):
        white = QColor(255, 255, 255, 235)
        cap_w = r * 0.42
        cap_h = r * 0.78
        cap = QRectF(cx - cap_w / 2, cy - cap_h * 0.62, cap_w, cap_h * 0.78)
        p.setPen(Qt.NoPen); p.setBrush(white)
        p.drawRoundedRect(cap, cap_w / 2, cap_w / 2)
        # дужка-держатель (U снизу капсулы)
        pen = QPen(white); pen.setWidthF(r * 0.085); pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        arc_w = cap_w * 1.7
        arc_rect = QRectF(cx - arc_w / 2, cy - cap_h * 0.30, arc_w, cap_h * 0.78)
        p.drawArc(arc_rect, 180 * 16, 180 * 16)
        # ножка + подставка
        stem_top = cy + cap_h * 0.30
        stem_bot = cy + cap_h * 0.52
        p.drawLine(QPointF(cx, stem_top), QPointF(cx, stem_bot))
        base_w = cap_w * 0.95
        p.drawLine(QPointF(cx - base_w / 2, stem_bot), QPointF(cx + base_w / 2, stem_bot))


class WaveformStrip(QWidget):
    """Живая полоса уровня: бегущие столбики, зеркальные относительно центра."""

    def __init__(self, parent=None, bars=46):
        super().__init__(parent)
        self.setFixedHeight(40)
        self._n = bars
        self._buf = deque([0.0] * bars, maxlen=bars)
        self._cur = 0.0
        self._active = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._scroll)
        self._timer.start(33)  # ~30 fps прокрутка

    def set_active(self, active):
        self._active = active
        if not active:
            self._cur = 0.0

    def set_level(self, rms):
        self._cur = min(1.0, rms * 14.0)

    def _scroll(self):
        if not self._active:
            self._cur *= 0.8
        self._buf.append(self._cur)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width(); h = self.height()
        cy = h / 2
        rgb = T.RGB["rec"] if self._active else T.RGB["border"]
        gap = 3.0
        bw = max(2.0, (w - gap * (self._n - 1)) / self._n)
        p.setPen(Qt.NoPen)
        for i, lv in enumerate(self._buf):
            x = i * (bw + gap)
            bh = max(2.0, lv * (h - 4))
            a = int(120 + 135 * lv) if self._active else 110
            p.setBrush(_c(rgb, a))
            p.drawRoundedRect(QRectF(x, cy - bh / 2, bw, bh), bw / 2, bw / 2)
        p.end()
