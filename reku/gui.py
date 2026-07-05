"""Reku — десктопный UI на PySide6. Frameless, тёмный, с анимированным
orb'ом, живым вэйвформом, настройками и треем. Фронт над движком DictationApp.

Запуск:  python gui.py   (или pythonw gui.py без консоли)
"""
import os
import sys

from reku import APP_NAME

if sys.stdout:
    print(f"{APP_NAME} UI: запускаюсь…", flush=True)

from PySide6.QtCore import Qt, QObject, Signal, QPoint, QSize, QTimer
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QLabel, QPushButton, QComboBox, QLineEdit,
    QVBoxLayout, QHBoxLayout, QStackedWidget, QGraphicsDropShadowEffect,
    QTextEdit, QPlainTextEdit, QRadioButton, QButtonGroup, QCheckBox,
    QSystemTrayIcon, QMenu, QSizePolicy, QSizeGrip, QScrollArea,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_SINGLE_KEY = "reku-single-instance"

from reku import gui_theme as T
from reku.gui_widgets import MicOrb, WaveformStrip, _c

# карты для комбобоксов настроек
MODELS = ["large-v3", "large-v3-turbo", "large-v2", "medium", "small", "base", "tiny"]
# "auto" — валидное значение конфига (дефолт); без него «применить настройки»
# молча подменяло compute_type на float16 и зря перегружало модель
COMPUTES = ["auto", "float16", "int8_float16", "int8", "float32"]
DEVICES = [("Авто", "auto"), ("GPU (CUDA)", "cuda"),
           ("Intel GPU (OpenVINO)", "igpu"), ("Intel NPU (эксперимент)", "npu"),
           ("CPU", "cpu"), ("API (облако)", "api")]
HOTKEYS = [("Right Ctrl", "ctrl_r"), ("Left Ctrl", "ctrl_l"),
           ("Right Alt", "alt_r"), ("Caps Lock", "caps_lock"),
           ("Right Shift", "shift_r"), ("F8", "f8"), ("F9", "f9")]
LANGS = [("Авто", ""), ("Русский", "ru"), ("English", "en"),
         ("Deutsch", "de"), ("Español", "es"), ("Українська", "uk")]
THEMES = [("Система", "system"), ("Светлая", "light"), ("Тёмная", "dark")]


class Bridge(QObject):
    """Мост из рабочих потоков движка в GUI-поток (сигналы потокобезопасны)."""
    stateChanged = Signal(str)
    resultReady = Signal(str)
    levelChanged = Signal(float)


def _safe_engine_call(fn, engine, bridge):
    """Зов метода движка в фоновом потоке: ошибка -> состояние 'error' в UI,
    а не молчаливая смерть потока (иначе окно вечно висит на «Скачиваю…»)."""
    try:
        fn()
    except Exception as e:
        print(f"[engine] {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        if engine is not None and getattr(engine, "_last_error", None) is None:
            engine._last_error = str(e)
        if bridge is not None:
            bridge.stateChanged.emit("error")


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
        title = QLabel(APP_NAME); title.setObjectName("TitleLabel")
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
    lab = QLabel(label); lab.setObjectName("RowLabel"); lab.setFixedWidth(96)
    lay.addWidget(lab); lay.addWidget(widget, 1)
    return w


_CHECK_URL = None


def _check_icon_url():
    """Путь к PNG-галочке для индикатора включённого чекбокса (QSS image:url). Белая
    галочка на синем (accent) фоне читается и в светлой, и в тёмной теме — одной хватает.
    Рисуем один раз в data_dir, путь — с прямыми слэшами (так его понимает QSS)."""
    global _CHECK_URL
    if _CHECK_URL:
        return _CHECK_URL
    try:
        from reku import config
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPen
        d = config.data_dir(); os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "check.png")
        pm = QPixmap(18, 18); pm.fill(Qt.transparent)
        p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(255, 255, 255)); pen.setWidthF(2.3)
        pen.setCapStyle(Qt.RoundCap); pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(4.0, 9.5), QPointF(7.5, 13.0), QPointF(14.0, 5.5)])
        p.end()
        pm.save(path, "PNG")
        _CHECK_URL = path.replace("\\", "/")
    except Exception as e:
        print(f"[theme] не смог нарисовать галочку чекбокса: {e}", file=sys.stderr)
        _CHECK_URL = None
    return _CHECK_URL


class MainWindow(QWidget):
    def __init__(self, cfg, engine=None, bridge=None):
        super().__init__()
        self.cfg = cfg
        self.engine = engine
        self.bridge = bridge
        self._state = "loading"

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(360, 460)
        self.resize(440, 640)            # дефолт с запасом под страницу настроек

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

        self._tray_refresh = None        # колбэк перерисовки иконки трея (ставит main())
        self.apply_theme()               # тёмная/светлая/системная из cfg.theme

        self._flashing = False
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._end_flash)

        self._grip = QSizeGrip(self)   # уголок для растягивания frameless-окна
        self._grip.setFixedSize(16, 16)

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

        lay.addStretch(1)

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
        inner = QWidget(); inner.setObjectName("SettingsInner")
        lay = QVBoxLayout(inner)
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
        self.device_combo = QComboBox()
        for label, val in DEVICES:
            self.device_combo.addItem(label, val)
        self._select_data(self.device_combo, self.cfg.device)
        # «API (облако)» — зарезервированное место (Фаза 2): видно, но неактивно
        _api_i = self.device_combo.findData("api")
        if _api_i >= 0:
            self.device_combo.model().item(_api_i).setEnabled(False)
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

        secU = QLabel("ОФОРМЛЕНИЕ"); secU.setObjectName("SectionLabel"); lay.addWidget(secU)
        self.theme_combo = QComboBox()
        for label, val in THEMES:
            self.theme_combo.addItem(label, val)
        self._select_data(self.theme_combo, self.cfg.theme)
        self.theme_combo.currentIndexChanged.connect(self._theme_changed)
        lay.addWidget(_row("Тема", self.theme_combo))

        sec3 = QLabel("РАСПОЗНАВАНИЕ"); sec3.setObjectName("SectionLabel"); lay.addWidget(sec3)
        self.vad_chk = QCheckBox("VAD — резать тишину/шум")
        self.vad_chk.setChecked(self.cfg.vad_filter)
        self.halluc_chk = QCheckBox("Фильтр галлюцинаций")
        self.halluc_chk.setChecked(self.cfg.drop_hallucinations)
        lay.addWidget(self.vad_chk); lay.addWidget(self.halluc_chk)

        vocab_lbl = QLabel("Словарь терминов"); vocab_lbl.setObjectName("RowLabel")
        lay.addWidget(vocab_lbl)
        self.vocab_edit = QPlainTextEdit()
        self.vocab_edit.setPlainText(self.cfg.hotwords)
        self.vocab_edit.setPlaceholderText(
            "термины через запятую или с новой строки\n(GitHub, OData, 1С, Docker…)")
        self.vocab_edit.setFixedHeight(76)
        lay.addWidget(self.vocab_edit)

        secS = QLabel("СИСТЕМА"); secS.setObjectName("SectionLabel"); lay.addWidget(secS)
        self.autostart_chk = QCheckBox("Запускать при старте Windows")
        try:
            from reku import autostart
            self.autostart_chk.setChecked(autostart.is_enabled())
        except Exception:
            self.autostart_chk.setEnabled(False)
        self.autostart_chk.toggled.connect(self._autostart_toggled)
        lay.addWidget(self.autostart_chk)

        lay.addStretch(1)
        self.apply_btn = QPushButton("Применить"); self.apply_btn.setObjectName("RecordBtn")
        self.apply_btn.setCursor(Qt.PointingHandCursor)
        self.apply_btn.clicked.connect(self._apply_settings)
        lay.addWidget(self.apply_btn)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        # НЕ зовём scroll.setStyleSheet(...) и НЕ делаем вьюпорт прозрачным: отдельный
        # стиль на контейнере обрывал каскад глобального #RecordBtn к кнопке «Применить»
        # внутри (она теряла синий фон и была невидима). Прозрачность не нужна — вьюпорт
        # красит palette(Window) = bg_window, что совпадает с карточкой (палитру ставит
        # apply_theme через T.build_palette, поэтому фон сходится в обеих темах).
        return scroll

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
        dev = ""
        b = getattr(self.engine, "backend", None) if self.engine else None
        if b is not None:
            label = b.device_label
            if self.cfg.device == "auto" and getattr(b, "device", None) == "cpu":
                label = "CPU (GPU не найден)"
            dev = " · " + label
        self.hint.setText(f"{key} · {mode}{dev}")

    # ── тема ─────────────────────────────────────────────────
    def apply_theme(self):
        """Применить тему из cfg.theme (system/dark/light). Зовётся при старте,
        смене темы в настройках и смене системной темы Windows."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        pal = T.resolve_theme(self.cfg.theme, app)
        self.setStyleSheet(T.set_active_theme(pal, _check_icon_url()))
        if app is not None:
            # палитра для нативных частей (всплывашка комбобокса, тултипы), которые QSS
            # не перекрывает — иначе в светлой теме они берут тёмную системную палитру
            app.setPalette(T.build_palette(pal))
        # перекрасить то, что QSS-перенакат не покрывает напрямую:
        self.titlebar.set_dot(T.STATE_RGB.get(self._state, T.RGB["accent"]))
        self.orb.update(); self.wave.update()
        if self._tray_refresh:
            self._tray_refresh(self._state)

    def _theme_changed(self):
        self.cfg.theme = self.theme_combo.currentData()
        from reku import config as _cfg; _cfg.save(self.cfg)
        self.apply_theme()

    def _autostart_toggled(self, on):
        try:
            from reku import autostart
            autostart.set_enabled(bool(on))
        except Exception as e:
            print(f"[autostart] {e}", file=sys.stderr)
            # реестр не изменился — откатываем чекбокс, иначе врёт пользователю
            self.autostart_chk.blockSignals(True)
            self.autostart_chk.setChecked(not on)
            self.autostart_chk.blockSignals(False)

    # ── состояние / результат / уровень ──────────────────────
    def set_state(self, state):
        self._state = state
        rgb = T.STATE_RGB.get(state, T.RGB["accent"])
        self.orb.set_state(state)
        if state != "idle":                 # новое действие — снять подтверждение
            self._flashing = False
            self._flash_timer.stop()
        if not self._flashing:
            self.status.setText(T.STATE_TEXT.get(state, state))
        self.titlebar.set_dot(rgb)
        self.wave.set_active(state == "recording")
        rec = state == "recording"
        self.rec_btn.setText("■ Стоп" if rec else "● Запись")
        self.rec_btn.setProperty("recording", "true" if rec else "false")
        self.rec_btn.style().unpolish(self.rec_btn); self.rec_btn.style().polish(self.rec_btn)
        busy = state not in ("idle", "recording")   # loading/downloading/transcribing/error
        self.rec_btn.setEnabled(not busy)
        if state == "idle":
            self._update_hint()
        elif state == "error":
            err = getattr(self.engine, "_last_error", None) if self.engine else None
            self.hint.setText(err or "Не удалось загрузить модель — проверьте устройство/сеть")

    def set_result(self, text):
        # текст уже вставлен в активное окно; в самой программе его не дублируем —
        # показываем лишь короткое подтверждение, что вставка прошла
        self.status.setText("✓ вставлено")
        self._flashing = True
        self._flash_timer.start(1500)

    def _end_flash(self):
        self._flashing = False
        self.status.setText(T.STATE_TEXT.get(self._state, self._state))

    def set_level(self, rms):
        self.orb.set_level(rms)
        self.wave.set_level(rms)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "_grip"):
            m = 8
            self._grip.move(self.width() - self._grip.width() - m,
                            self.height() - self._grip.height() - m)
            self._grip.raise_()

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
        from reku import config as _cfg; _cfg.save(self.cfg)
        if self.engine:
            self.engine.apply_config()
        self._update_hint()

    def _apply_settings(self):
        from reku import config as _cfg
        c = self.cfg
        old = (c.model, c.device, c.compute_type)
        c.model = self.model_combo.currentText()
        c.device = self.device_combo.currentData()
        c.compute_type = self.compute_combo.currentText()
        c.hotkey = self.hotkey_combo.currentData()
        c.mode = "toggle" if self.tog_radio.isChecked() else "ptt"
        c.vad_filter = self.vad_chk.isChecked()
        c.drop_hallucinations = self.halluc_chk.isChecked()
        # многострочный ввод -> чистый список «через запятую» (по строкам и запятым)
        c.hotwords = ", ".join(s.strip() for s in self.vocab_edit.toPlainText().splitlines()
                               if s.strip())
        _cfg.save(c)
        if self.engine:
            self.engine.apply_config()
        self._update_hint()
        self._select_data(self.lang_combo, c.language)
        self.stack.setCurrentIndex(0)
        if self.engine and (c.model, c.device, c.compute_type) != old:
            import threading
            self.set_state("loading")
            threading.Thread(target=lambda: self._reload_with_rollback(old),
                             daemon=True).start()

    def _reload_with_rollback(self, old):
        """reload_model в фоне; при ошибке — откатить model/device/compute_type
        в config.json и поднять прежний рабочий бэкенд. Иначе нерабочий выбор
        (нет такого устройства / модель не поднялась) застревает в конфиге,
        и каждый следующий запуск приложения падает так же."""
        from reku import config as _cfg
        emit = self.bridge.stateChanged.emit if self.bridge else self.set_state
        try:
            if not self.engine.reload_model():   # False = движок занят записью
                emit("idle")                     # не виснуть в loading
        except Exception as e:
            print(f"[engine] {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            c = self.cfg
            c.model, c.device, c.compute_type = old
            _cfg.save(c)
            self.engine._last_error = f"{str(e)[:100]} — настройки откачены"
            emit("error")
            _safe_engine_call(self.engine.reload_model, self.engine, self.bridge)

    def hide_to_tray(self):
        self.hide()

    def show_normal(self):
        self.showNormal(); self.raise_(); self.activateWindow()

    def closeEvent(self, e):
        e.ignore(); self.hide()


# ── иконка трея (кружок + микрофон, цвет = статус) ───────────
def make_icon(rgb):
    """Иконка трея/приложения: «squircle» бренд-цвета (статус) + крупный белый микрофон.
    Рисуем в 64px, заполняя почти весь холст — так читается даже в мелком трее (16-24px)."""
    from PySide6.QtGui import QPen, QLinearGradient, QBrush
    r, g, b = rgb
    pm = QPixmap(64, 64); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
    # фон — скруглённый квадрат с лёгким вертикальным градиентом (объём)
    grad = QLinearGradient(0, 4, 0, 60)
    grad.setColorAt(0.0, QColor(min(255, r + 26), min(255, g + 26), min(255, b + 26)))
    grad.setColorAt(1.0, QColor(r, g, b))
    p.setPen(Qt.NoPen); p.setBrush(QBrush(grad))
    p.drawRoundedRect(4, 4, 56, 56, 18, 18)
    # микрофон — белый, по центру, жирный
    white = QColor(255, 255, 255, 242)
    p.setBrush(white); p.setPen(Qt.NoPen)
    p.drawRoundedRect(25, 14, 14, 23, 7, 7)              # капсула
    pen = QPen(white); pen.setWidthF(3.6); pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen); p.setBrush(Qt.NoBrush)
    p.drawArc(18, 23, 28, 27, 180 * 16, 180 * 16)        # дужка-держатель (U снизу капсулы)
    p.drawLine(32, 46, 32, 52)                            # ножка
    p.drawLine(24, 52, 40, 52)                            # подставка
    p.end()
    return QIcon(pm)


def _run_selftest():
    """Headless-самопроверка собранного .exe (REKU_SELFTEST=1).
    UI не поднимаем: грузим модель, делаем короткую транскрипцию тишины,
    пишем результат в %APPDATA%/Reku/selftest.json и выходим.
    Главное — убедиться, что ct2 ВИДИТ CUDA (а не молча ушёл на CPU из-за
    непойманной DLL). test_frozen_smoke.py читает этот json."""
    import json
    import numpy as np
    from reku import config
    from reku import cuda_setup
    from reku import backends
    from reku.dictate import DictationApp

    result = {"cuda_device_count": 0, "device": None, "transcribe_ok": False,
              "added_dll_dirs": list(getattr(cuda_setup, "_ADDED", [])), "error": None}
    try:
        try:
            import ctranslate2
            result["cuda_device_count"] = ctranslate2.get_cuda_device_count()
        except Exception as e:
            result["error"] = f"ct2 import/cuda: {e}"

        cfg = config.load()
        app = DictationApp(cfg)
        app.load_model()
        result["device"] = app.backend.device
        silence = np.zeros(cfg.sample_rate, dtype=np.float32)
        app.transcribe(silence)        # не должно бросать исключение
        result["transcribe_ok"] = True
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

    out = os.path.join(config.data_dir(), "selftest.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("[selftest]", json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if (result["device"] and result["transcribe_ok"]) else 1


def main():
    import threading
    from reku import config
    from reku.dictate import DictationApp

    if os.environ.get("REKU_SELFTEST") == "1":
        sys.exit(_run_selftest())

    app = QApplication(sys.argv)
    app.setStyle("Fusion")                 # стабильная отрисовка QSS+палитры на всех
                                           # платформах: нативный Win-стиль игнорирует
                                           # часть стилей (тёмная всплывашка, бледная кнопка)
    app.setQuitOnLastWindowClosed(False)   # закрытие окна → в трей, не выход

    # single-instance: если уже запущено — показать то окно и выйти
    _probe = QLocalSocket()
    _probe.connectToServer(_SINGLE_KEY)
    if _probe.waitForConnected(200):
        _probe.write(b"show"); _probe.flush(); _probe.waitForBytesWritten(300)
        sys.exit(0)
    QLocalServer.removeServer(_SINGLE_KEY)
    _server = QLocalServer()
    _server.listen(_SINGLE_KEY)

    cfg = config.load()

    bridge = Bridge()
    engine = DictationApp(
        cfg,
        on_state=bridge.stateChanged.emit,
        on_result=bridge.resultReady.emit,
        on_level=bridge.levelChanged.emit,
    )
    win = MainWindow(cfg, engine=engine, bridge=bridge)

    def _on_second_instance():
        conn = _server.nextPendingConnection()
        if conn is not None:
            conn.readyRead.connect(lambda: (conn.readAll(), win.show_normal()))
    _server.newConnection.connect(_on_second_instance)

    # системный трей
    tray = QSystemTrayIcon(make_icon(T.STATE_RGB["loading"]), app)
    tray.setToolTip(f"{APP_NAME} — загрузка…")
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
        tray.setToolTip(f"{APP_NAME} — {T.STATE_TEXT.get(s, s)}")
    bridge.stateChanged.connect(on_tray_state)

    # перерисовать иконку трея при смене темы + следовать системной теме на лету
    win._tray_refresh = on_tray_state
    app.styleHints().colorSchemeChanged.connect(
        lambda *_: win.apply_theme() if win.cfg.theme == "system" else None)

    win.show()
    threading.Thread(target=lambda: _safe_engine_call(engine.start, engine, bridge),
                     daemon=True).start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
