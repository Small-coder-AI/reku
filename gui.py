"""whisper_ptt — десктопный UI на PySide6. Frameless, тёмный, с анимированным
orb'ом, живым вэйвформом, настройками и треем. Фронт над движком DictationApp.

Запуск:  python gui.py   (или pythonw gui.py без консоли)
"""
import sys

if sys.stdout:
    print("whisper_ptt UI: запускаюсь…", flush=True)

from PySide6.QtCore import Qt, QObject, Signal, QPoint, QSize, QTimer
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QLabel, QPushButton, QComboBox, QLineEdit,
    QVBoxLayout, QHBoxLayout, QStackedWidget, QGraphicsDropShadowEffect,
    QTextEdit, QRadioButton, QButtonGroup, QCheckBox, QSystemTrayIcon, QMenu,
    QSizePolicy,
)

import gui_theme as T
from gui_widgets import MicOrb, WaveformStrip, _c

# карты для комбобоксов настроек
MODELS = ["large-v3", "large-v2", "medium", "small", "base", "tiny"]
COMPUTES = ["float16", "int8_float16", "int8", "float32"]
DEVICES = ["cuda", "cpu"]
HOTKEYS = [("Right Ctrl", "ctrl_r"), ("Left Ctrl", "ctrl_l"),
           ("Right Alt", "alt_r"), ("Caps Lock", "caps_lock"),
           ("Right Shift", "shift_r"), ("F8", "f8"), ("F9", "f9")]
LANGS = [("Авто", ""), ("Русский", "ru"), ("English", "en"),
         ("Deutsch", "de"), ("Español", "es"), ("Українська", "uk")]


class Bridge(QObject):
    """Мост из рабочих потоков движка в GUI-поток (сигналы потокобезопасны)."""
    stateChanged = Signal(str)
    resultReady = Signal(str)
    levelChanged = Signal(float)


# ── заголовок окна (перетаскивание + кнопки) ─────────────────
class TitleBar(QWidget):
    def __init__(self, win):
        super().__init__()
        self._win = win
        self._drag = None
        self.setFixedHeight(40)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 10, 0)
        lay.setSpacing(8)

        self.dot = QLabel("●")
        self.dot.setStyleSheet(f"color: {T.ACCENT}; font-size: 11px;")
        title = QLabel("whisper_ptt"); title.setObjectName("TitleLabel")
        lay.addWidget(self.dot); lay.addWidget(title)
        lay.addStretch(1)

        mini = QPushButton("—"); mini.setObjectName("WinBtn")
        mini.setFixedSize(28, 28); mini.clicked.connect(win.showMinimized)
        close = QPushButton("✕"); close.setObjectName("WinBtn")
        close.setProperty("class", "close")
        close.setObjectName("CloseBtn"); close.setFixedSize(28, 28)
        close.clicked.connect(win.hide_to_tray)
        lay.addWidget(mini); lay.addWidget(close)

    def set_dot(self, rgb):
        self.dot.setStyleSheet(f"color: rgb({rgb[0]},{rgb[1]},{rgb[2]}); font-size: 11px;")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self._win.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None


def _row(label, widget):
    w = QWidget(); lay = QHBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0)
    lab = QLabel(label); lab.setStyleSheet(f"color: {T.TEXT_2};"); lab.setFixedWidth(96)
    lay.addWidget(lab); lay.addWidget(widget, 1)
    return w


class MainWindow(QWidget):
    def __init__(self, cfg, engine=None, bridge=None):
        super().__init__()
        self.cfg = cfg
        self.engine = engine
        self.bridge = bridge
        self._state = "loading"

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(384, 540)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 18)  # место под тень
        self.card = QFrame(); self.card.setObjectName("Card")
        outer.addWidget(self.card)
        shadow = QGraphicsDropShadowEffect(blurRadius=40, xOffset=0, yOffset=8)
        shadow.setColor(QColor(0, 0, 0, 190))
        self.card.setGraphicsEffect(shadow)

        root = QVBoxLayout(self.card)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        self.titlebar = TitleBar(self)
        root.addWidget(self.titlebar)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.stack.addWidget(self._build_main_page())
        self.stack.addWidget(self._build_settings_page())

        self.setStyleSheet(T.QSS)
        self.set_state("loading")

        if self.bridge is not None:
            self.bridge.stateChanged.connect(self.set_state)
            self.bridge.resultReady.connect(self.set_result)
            self.bridge.levelChanged.connect(self.set_level)

    # ── главная страница ─────────────────────────────────────
    def _build_main_page(self):
        page = QWidget(); lay = QVBoxLayout(page)
        lay.setContentsMargins(22, 6, 22, 20); lay.setSpacing(0)

        lay.addStretch(1)
        orb_row = QHBoxLayout(); orb_row.addStretch(1)
        self.orb = MicOrb(size=172); orb_row.addWidget(self.orb)
        orb_row.addStretch(1); lay.addLayout(orb_row)

        lay.addSpacing(14)
        self.status = QLabel("Готов"); self.status.setObjectName("StatusLabel")
        self.status.setAlignment(Qt.AlignCenter); lay.addWidget(self.status)

        lay.addSpacing(4)
        self.hint = QLabel(""); self.hint.setObjectName("HintLabel")
        self.hint.setAlignment(Qt.AlignCenter); lay.addWidget(self.hint)
        self._update_hint()

        lay.addSpacing(16)
        self.wave = WaveformStrip(); lay.addWidget(self.wave)

        lay.addSpacing(16)
        tcard = QFrame(); tcard.setObjectName("TextCard")
        tcard.setMinimumHeight(96)
        tlay = QVBoxLayout(tcard); tlay.setContentsMargins(14, 10, 8, 10)
        self.text = QTextEdit(); self.text.setObjectName("TextView")
        self.text.setReadOnly(True)
        self.text.setPlaceholderText("Здесь появится распознанный текст…")
        tlay.addWidget(self.text)
        lay.addWidget(tcard)

        lay.addSpacing(14)
        bottom = QHBoxLayout(); bottom.setSpacing(10)
        self.rec_btn = QPushButton("● Запись"); self.rec_btn.setObjectName("RecordBtn")
        self.rec_btn.setCursor(Qt.PointingHandCursor)
        self.rec_btn.clicked.connect(self._toggle_record)
        bottom.addWidget(self.rec_btn, 1)

        self.lang_combo = QComboBox()
        for label, val in LANGS:
            self.lang_combo.addItem(label, val)
        self._select_data(self.lang_combo, self.cfg.language)
        self.lang_combo.setFixedWidth(104)
        self.lang_combo.currentIndexChanged.connect(self._lang_changed)
        bottom.addWidget(self.lang_combo)

        gear = QPushButton("⚙"); gear.setObjectName("IconBtn")
        gear.setFixedSize(40, 38); gear.setCursor(Qt.PointingHandCursor)
        gear.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        bottom.addWidget(gear)
        lay.addLayout(bottom)
        return page

    # ── страница настроек ────────────────────────────────────
    def _build_settings_page(self):
        page = QWidget(); lay = QVBoxLayout(page)
        lay.setContentsMargins(22, 8, 22, 20); lay.setSpacing(12)

        head = QHBoxLayout()
        back = QPushButton("←"); back.setObjectName("IconBtn")
        back.setFixedSize(36, 34); back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        ttl = QLabel("Настройки"); ttl.setObjectName("TitleLabel")
        head.addWidget(back); head.addSpacing(6); head.addWidget(ttl); head.addStretch(1)
        lay.addLayout(head)

        sec1 = QLabel("МОДЕЛЬ"); sec1.setObjectName("SectionLabel"); lay.addWidget(sec1)
        self.model_combo = QComboBox(); self.model_combo.addItems(MODELS)
        self._select_text(self.model_combo, self.cfg.model)
        self.device_combo = QComboBox(); self.device_combo.addItems(DEVICES)
        self._select_text(self.device_combo, self.cfg.device)
        self.compute_combo = QComboBox(); self.compute_combo.addItems(COMPUTES)
        self._select_text(self.compute_combo, self.cfg.compute_type)
        lay.addWidget(_row("Модель", self.model_combo))
        lay.addWidget(_row("Устройство", self.device_combo))
        lay.addWidget(_row("Точность", self.compute_combo))

        sec2 = QLabel("ВВОД"); sec2.setObjectName("SectionLabel"); lay.addWidget(sec2)
        self.hotkey_combo = QComboBox()
        for label, val in HOTKEYS:
            self.hotkey_combo.addItem(label, val)
        self._select_data(self.hotkey_combo, self.cfg.hotkey)
        lay.addWidget(_row("Хоткей", self.hotkey_combo))

        modew = QWidget(); ml = QHBoxLayout(modew); ml.setContentsMargins(0, 0, 0, 0)
        self.ptt_radio = QRadioButton("PTT (зажим)")
        self.tog_radio = QRadioButton("Toggle")
        grp = QButtonGroup(self); grp.addButton(self.ptt_radio); grp.addButton(self.tog_radio)
        (self.tog_radio if self.cfg.mode == "toggle" else self.ptt_radio).setChecked(True)
        ml.addWidget(self.ptt_radio); ml.addWidget(self.tog_radio); ml.addStretch(1)
        lay.addWidget(_row("Режим", modew))

        sec3 = QLabel("РАСПОЗНАВАНИЕ"); sec3.setObjectName("SectionLabel"); lay.addWidget(sec3)
        self.vad_chk = QCheckBox("VAD — резать тишину/шум")
        self.vad_chk.setChecked(self.cfg.vad_filter)
        self.halluc_chk = QCheckBox("Фильтр галлюцинаций")
        self.halluc_chk.setChecked(self.cfg.drop_hallucinations)
        lay.addWidget(self.vad_chk); lay.addWidget(self.halluc_chk)

        lay.addStretch(1)
        self.apply_btn = QPushButton("Применить"); self.apply_btn.setObjectName("RecordBtn")
        self.apply_btn.setCursor(Qt.PointingHandCursor)
        self.apply_btn.clicked.connect(self._apply_settings)
        lay.addWidget(self.apply_btn)
        return page

    # ── helpers выбора в комбобоксах ─────────────────────────
    @staticmethod
    def _select_text(combo, value):
        i = combo.findText(value)
        if i >= 0:
            combo.setCurrentIndex(i)

    @staticmethod
    def _select_data(combo, value):
        i = combo.findData(value)
        combo.setCurrentIndex(i if i >= 0 else 0)

    def _update_hint(self):
        names = {v: l for l, v in HOTKEYS}
        key = names.get(self.cfg.hotkey, self.cfg.hotkey)
        mode = "PTT" if self.cfg.mode == "ptt" else "Toggle"
        self.hint.setText(f"{key} · {mode}")

    # ── состояние / результат / уровень ──────────────────────
    def set_state(self, state):
        self._state = state
        rgb = T.STATE_RGB.get(state, T.RGB["accent"])
        self.orb.set_state(state)
        self.status.setText(T.STATE_TEXT.get(state, state))
        self.titlebar.set_dot(rgb)
        self.wave.set_active(state == "recording")
        rec = state == "recording"
        self.rec_btn.setText("■ Стоп" if rec else "● Запись")
        self.rec_btn.setProperty("recording", "true" if rec else "false")
        self.rec_btn.style().unpolish(self.rec_btn); self.rec_btn.style().polish(self.rec_btn)
        busy = state in ("loading", "transcribing")
        self.rec_btn.setEnabled(not busy)

    def set_result(self, text):
        self.text.setPlainText(text)

    def set_level(self, rms):
        self.orb.set_level(rms)
        self.wave.set_level(rms)

    # ── действия ─────────────────────────────────────────────
    def _toggle_record(self):
        if self.engine is None:
            return
        import threading
        if self._state == "recording":
            threading.Thread(target=self.engine.stop_and_transcribe, daemon=True).start()
        elif self._state == "idle":
            self.engine.start_rec()

    def _lang_changed(self):
        self.cfg.language = self.lang_combo.currentData()
        import config as _cfg; _cfg.save(self.cfg)
        if self.engine:
            self.engine.apply_config()
        self._update_hint()

    def _apply_settings(self):
        import config as _cfg
        c = self.cfg
        old = (c.model, c.device, c.compute_type)
        c.model = self.model_combo.currentText()
        c.device = self.device_combo.currentText()
        c.compute_type = self.compute_combo.currentText()
        c.hotkey = self.hotkey_combo.currentData()
        c.mode = "toggle" if self.tog_radio.isChecked() else "ptt"
        c.vad_filter = self.vad_chk.isChecked()
        c.drop_hallucinations = self.halluc_chk.isChecked()
        _cfg.save(c)
        if self.engine:
            self.engine.apply_config()
        self._update_hint()
        self._select_data(self.lang_combo, c.language)
        self.stack.setCurrentIndex(0)
        if self.engine and (c.model, c.device, c.compute_type) != old:
            import threading
            self.set_state("loading")
            threading.Thread(target=self.engine.reload_model, daemon=True).start()

    def hide_to_tray(self):
        self.hide()

    def show_normal(self):
        self.showNormal(); self.raise_(); self.activateWindow()

    def closeEvent(self, e):
        e.ignore(); self.hide()


# ── иконка трея (кружок + микрофон, цвет = статус) ───────────
def make_icon(rgb):
    from PySide6.QtGui import QPen
    pm = QPixmap(64, 64); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen); p.setBrush(QColor(rgb[0], rgb[1], rgb[2]))
    p.drawEllipse(5, 5, 54, 54)
    white = QColor(255, 255, 255, 235)
    p.setBrush(white); p.drawRoundedRect(26, 16, 12, 21, 6, 6)
    pen = QPen(white); pen.setWidth(3); pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen); p.setBrush(Qt.NoBrush)
    p.drawArc(20, 27, 24, 22, 180 * 16, 180 * 16)
    p.drawLine(32, 39, 32, 47)
    p.drawLine(25, 47, 39, 47)
    p.end()
    return QIcon(pm)


def main():
    import threading
    import config
    from dictate import DictationApp

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)   # закрытие окна → в трей, не выход
    cfg = config.load()

    bridge = Bridge()
    engine = DictationApp(
        cfg,
        on_state=bridge.stateChanged.emit,
        on_result=bridge.resultReady.emit,
        on_level=bridge.levelChanged.emit,
    )
    win = MainWindow(cfg, engine=engine, bridge=bridge)

    # системный трей
    tray = QSystemTrayIcon(make_icon(T.STATE_RGB["loading"]), app)
    tray.setToolTip("whisper_ptt — загрузка…")
    menu = QMenu()
    menu.addAction("Показать").triggered.connect(win.show_normal)
    menu.addSeparator()

    def quit_all():
        try:
            engine.stop()
        finally:
            tray.hide(); app.quit()

    menu.addAction("Выход").triggered.connect(quit_all)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: win.show_normal()
        if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()

    def on_tray_state(s):
        rgb = T.STATE_RGB.get(s, T.RGB["accent"])
        tray.setIcon(make_icon(rgb))
        tray.setToolTip(f"whisper_ptt — {T.STATE_TEXT.get(s, s)}")
    bridge.stateChanged.connect(on_tray_state)

    win.show()
    threading.Thread(target=engine.start, daemon=True).start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
