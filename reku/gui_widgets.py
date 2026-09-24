"""Кастомные рисованные виджеты: MicOrb (анимированный), WaveformStrip и
рисованные (не шрифтовые) line-иконки кнопок."""
import math
from collections import deque

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QRadialGradient, QPen, QBrush, QIcon, QPixmap
from PySide6.QtWidgets import QWidget

from reku import gui_theme as T


def _c(rgb, a=255):
    return QColor(rgb[0], rgb[1], rgb[2], a)


# ── line-иконки кнопок (закрыть/свернуть/назад/шестерёнка) ───────────────
# Рисуем QPainter'ом, а не шрифтовым глифом (⚙ ← — ✕): глиф зависит от
# установленного эмодзи-шрифта и не всегда в тон палитре; свой рисунок —
# всегда чёткий и нужного цвета.
_ICON_STROKE = 1.6


def _paint_icon(kind, p, s):
    """Отрисовать один глиф в логических координатах [0, s] x [0, s]."""
    if kind == "close":
        m = s * 0.28
        p.drawLine(QPointF(m, m), QPointF(s - m, s - m))
        p.drawLine(QPointF(s - m, m), QPointF(m, s - m))
    elif kind == "minimize":
        y = s * 0.5
        p.drawLine(QPointF(s * 0.24, y), QPointF(s * 0.76, y))
    elif kind == "back":
        y = s * 0.5
        p.drawLine(QPointF(s * 0.28, y), QPointF(s * 0.78, y))
        p.drawPolyline([QPointF(s * 0.50, s * 0.24), QPointF(s * 0.26, y),
                        QPointF(s * 0.50, s * 0.76)])
    elif kind == "gear":
        cx = cy = s * 0.5
        r_outer = s * 0.28
        r_hole = s * 0.11
        p.drawEllipse(QPointF(cx, cy), r_outer, r_outer)
        p.drawEllipse(QPointF(cx, cy), r_hole, r_hole)
        teeth = 8
        tooth = s * 0.12
        for i in range(teeth):
            ang = 2 * math.pi * i / teeth
            x1, y1 = cx + math.cos(ang) * r_outer, cy + math.sin(ang) * r_outer
            x2 = cx + math.cos(ang) * (r_outer + tooth)
            y2 = cy + math.sin(ang) * (r_outer + tooth)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    else:
        raise ValueError(f"неизвестная иконка: {kind}")


def draw_icon(kind: str, color, size: int = 16, dpr: float = 2.0) -> QIcon:
    """Рисованная (не шрифтовая) line-иконка кнопки: 'close'/'minimize'/'back'/'gear'.
    color — из активной палитры (обычно text2), чтобы иконка была в тон теме.
    HiDPI: пиксмап физически в dpr раз крупнее, devicePixelRatio проставлен явно —
    иконка остаётся чёткой на масштабированных экранах. Зовём заново в
    MainWindow.apply_theme при каждой смене темы (цвет ведь меняется)."""
    px = QPixmap(round(size * dpr), round(size * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(_ICON_STROKE)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    _paint_icon(kind, p, size)
    p.end()
    return QIcon(px)


class MicOrb(QWidget):
    """Светящийся орб с микрофоном. Дышит (idle), пульсирует по уровню (rec),
    крутит дугу (transcribing). Перерисовку ведёт только таймер _tick (не
    set_level — его дёргают ~100 раз/с из аудиопотока, апдейт на каждый вызов
    держал окно на ~40% CPU во время записи); частота тика зависит от
    состояния, а офскрин-рендер (фазу можно выставить вручную перед grab)
    от этого не страдает — paintEvent как и раньше не требует тика."""

    _TICK_MS_ACTIVE = 33   # ~30 fps — запись/распознавание, нужна плавность пульса/дуги
    _TICK_MS_IDLE = 70     # ~14 fps — дыхание в покое, глазу хватает и такого
    _ANIMATED = ("idle", "recording", "transcribing")   # прочие состояния рисуются статично

    def __init__(self, parent=None, size=168):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._state = "idle"
        self._level = 0.0       # сглаженный уровень 0..1
        self._phase = 0.0       # фаза анимации
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        # таймер стартует в showEvent — не тикать, пока виджет не показан

    def set_state(self, state):
        self._state = state
        self._sync_timer()
        self.update()

    def set_level(self, rms):
        """Только копит сглаженный уровень — перерисовку ведёт таймер _tick."""
        target = min(1.0, rms * 14.0)
        # атака быстрая, спад плавный
        if target > self._level:
            self._level += (target - self._level) * 0.5
        else:
            self._level += (target - self._level) * 0.15

    def _tick(self):
        self._phase += 0.045
        if self._state != "recording":
            self._level *= 0.85   # затухание, когда не пишем
        self.update()

    def _sync_timer(self):
        """Тикать только пока виджет виден и есть что анимировать: loading/
        downloading/error рисуются с постоянным pulse — им перерисовка не нужна."""
        if not self.isVisible() or self._state not in self._ANIMATED:
            self._timer.stop()
            return
        fast = self._state in ("recording", "transcribing")
        self._timer.start(self._TICK_MS_ACTIVE if fast else self._TICK_MS_IDLE)

    def showEvent(self, e):
        super().showEvent(e)
        self._sync_timer()

    def hideEvent(self, e):
        self._timer.stop()   # окно ушло в трей/на другую страницу — анимировать некому
        super().hideEvent(e)

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
    """Живая полоса уровня: бегущие столбики, зеркальные относительно центра.
    Таймер прокрутки работает, только пока есть что показывать (идёт запись
    или старые столбики ещё не затухли до нуля) и виджет виден — иначе стоит."""

    def __init__(self, parent=None, bars=46):
        super().__init__(parent)
        self.setFixedHeight(40)
        self._n = bars
        self._buf = deque([0.0] * bars, maxlen=bars)
        self._cur = 0.0
        self._active = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._scroll)
        # таймер стартует по требованию (_sync_timer) — не крутится вхолостую

    def set_active(self, active):
        self._active = active
        if not active:
            self._cur = 0.0
        self._sync_timer()

    def set_level(self, rms):
        """Только копит целевой уровень — перерисовку ведёт таймер _scroll."""
        self._cur = min(1.0, rms * 14.0)

    def _scroll(self):
        if not self._active:
            self._cur *= 0.8
        self._buf.append(self._cur)
        self.update()
        self._sync_timer()   # все столбики выдохлись до нуля -> можно остановиться

    def _sync_timer(self):
        if not self.isVisible():
            self._timer.stop()
            return
        needed = self._active or any(v > 0.005 for v in self._buf)
        if needed:
            if not self._timer.isActive():
                self._timer.start(33)  # ~30 fps прокрутка
        else:
            self._timer.stop()

    def showEvent(self, e):
        super().showEvent(e)
        self._sync_timer()

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

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
