"""Reku — десктопный UI на PySide6. Frameless, тёмный, с анимированным
orb'ом, живым вэйвформом, настройками и треем. Фронт над движком DictationApp.

Запуск:  python gui.py   (или pythonw gui.py без консоли)
"""
import os
import sys

# Первым делом — лог старта: под pythonw stdout/stderr нет, и без этого любая
# ошибка ниже (вплоть до битого PySide6) умирает молча. Строго до остальных импортов.
from reku import startlog
startlog.init()

from reku import APP_NAME

if sys.stdout:
    print(f"{APP_NAME} UI: запускаюсь…", flush=True)

# Обход краша на Python 3.12.0: import-хук shiboken (его ставит импорт PySide6)
# зовёт inspect.getsource для каждого нового модуля; на fake-модулях six
# (six.moves.*, их тянет pynput) это TypeError, чьё форматирование на 3.12.0
# падает вторичным AttributeError ('_SixMetaPathImporter' без '_path') — процесс
# умирает на старте. Импортируем pynput ДО PySide6: six.moves попадает в
# sys.modules раньше, чем встаёт хук. Боевой случай 2026-07 (Python 3.12.0);
# на 3.12.10 не воспроизводится. Не переносить ниже PySide6!
import pynput  # noqa: F401

from PySide6.QtCore import Qt, QObject, QEvent, Signal, QSize, QTimer
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QLabel, QPushButton, QComboBox,
    QVBoxLayout, QHBoxLayout, QStackedWidget, QGraphicsDropShadowEffect,
    QPlainTextEdit, QRadioButton, QButtonGroup, QCheckBox,
    QSystemTrayIcon, QMenu, QScrollArea,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_SINGLE_KEY = "reku-single-instance"

from reku import gui_resize
from reku import gui_theme as T
from reku.gui_overlay import RecordingOverlay
from reku.gui_widgets import MicOrb, WaveformStrip, draw_icon

DEFAULT_SIZE = (440, 660)   # влезают и главная страница, и настройки без прокрутки
MIN_SIZE = (360, 460)
_SCROLL_INSET = gui_resize.BAND_IN + 3   # отступ полосы прокрутки настроек от края

# карты для комбобоксов настроек
MODELS = ["large-v3", "large-v3-turbo", "large-v2", "medium", "small", "base", "tiny"]
# "auto" — валидное значение конфига (дефолт); без него «применить настройки»
# молча подменяло compute_type на float16 и зря перегружало модель
COMPUTES = ["auto", "float16", "int8_float16", "int8", "float32"]
DEVICES = [("Авто", "auto"), ("GPU (CUDA)", "cuda"),
           ("Intel GPU (OpenVINO)", "igpu"), ("Intel NPU (эксперимент)", "npu"),
           ("AMD GPU (Vulkan)", "amd"),
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

        self.mini_btn = QPushButton(); self.mini_btn.setObjectName("WinBtn")
        self.mini_btn.setFixedSize(28, 28)
        self.mini_btn.clicked.connect(win.showMinimized)
        self.close_btn = QPushButton(); self.close_btn.setObjectName("WinBtn")
        self.close_btn.setProperty("role", "close")   # для красного hover в QSS
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.clicked.connect(win.hide_to_tray)
        lay.addWidget(self.mini_btn); lay.addWidget(self.close_btn)
        self.update_icons(T.ACTIVE.text2)

    def update_icons(self, color):
        """Перерисовать иконки свернуть/закрыть под цвет активной темы."""
        size = QSize(14, 14)
        self.mini_btn.setIcon(draw_icon("minimize", color, size=14))
        self.mini_btn.setIconSize(size)
        self.close_btn.setIcon(draw_icon("close", color, size=14))
        self.close_btn.setIconSize(size)

    def set_dot(self, rgb):
        self.dot.setStyleSheet(f"color: rgb({rgb[0]},{rgb[1]},{rgb[2]}); font-size: 11px;")

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        handle = self.window().windowHandle()
        if handle is not None and handle.startSystemMove():
            # система сама ведёт перетаскивание (даёт Aero Snap на Windows) —
            # свой mouseMoveEvent-фолбэк не нужен
            self._drag = None
            return
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


def _section(title):
    lab = QLabel(title); lab.setObjectName("SectionLabel")
    return lab


class _WheelGuard(QObject):
    """Колесо мыши над комбобоксом без фокуса прокручивает страницу, а не меняет
    значение: иначе, листая настройки, можно молча сменить модель или хоткей."""

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.Wheel and not obj.hasFocus():
            e.ignore()          # событие уйдёт родителю — области прокрутки
            return True
        return False


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
    # из фонового потока перезагрузки в GUI-поток: движок был занят, повторить позже
    _reloadDeferred = Signal(object)

    def __init__(self, cfg, engine=None, bridge=None):
        super().__init__()
        self.cfg = cfg
        self.engine = engine
        self.bridge = bridge
        self._state = "loading"

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(*MIN_SIZE)
        self._restore_size()

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
        self._pending_reload = None      # смена модели, отложенная до конца записи
        self._reloadDeferred.connect(self._start_reload)
        self.apply_theme()               # тёмная/светлая/системная из cfg.theme

        self._flashing = False
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._end_flash)

        # растянутый размер окна запоминаем, когда пользователь отпустил край
        self._size_timer = QTimer(self)
        self._size_timer.setSingleShot(True)
        self._size_timer.timeout.connect(self._save_size)

        self.overlay = RecordingOverlay(cfg)   # плашка «Запись…» поверх всех окон

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
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)   # длинное сообщение об ошибке переносится, не режется
        self.hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.hint)
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

        self.gear_btn = QPushButton(); self.gear_btn.setObjectName("IconBtn")
        self.gear_btn.setFixedSize(40, 38); self.gear_btn.setCursor(Qt.PointingHandCursor)
        self.gear_btn.clicked.connect(self._open_settings)
        bottom.addWidget(self.gear_btn)
        lay.addLayout(bottom)
        return page

    # ── страница настроек ────────────────────────────────────
    def _build_settings_page(self):
        """Шапка и «Применить» — вне прокрутки: видны при любом размере окна.
        Прокручивается только список; редкие настройки свёрнуты в «Дополнительно»."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        head = QHBoxLayout(); head.setContentsMargins(22, 4, 22, 6)
        self.back_btn = QPushButton(); self.back_btn.setObjectName("IconBtn")
        self.back_btn.setFixedSize(36, 34); self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        ttl = QLabel("Настройки"); ttl.setObjectName("TitleLabel")
        head.addWidget(self.back_btn); head.addSpacing(6); head.addWidget(ttl); head.addStretch(1)
        outer.addLayout(head)

        inner = QWidget(); inner.setObjectName("SettingsInner")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(22, 0, 22 - _SCROLL_INSET, 10); lay.setSpacing(8)

        lay.addWidget(_section("РАСПОЗНАВАНИЕ"))
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
        lay.addWidget(_row("Модель", self.model_combo))
        lay.addWidget(_row("Устройство", self.device_combo))

        vocab_lbl = QLabel("Словарь терминов"); vocab_lbl.setObjectName("RowLabel")
        lay.addWidget(vocab_lbl)
        self.vocab_edit = QPlainTextEdit()
        self.vocab_edit.setPlainText(self.cfg.hotwords)
        self.vocab_edit.setPlaceholderText(
            "термины через запятую или с новой строки\n(например: GitHub, Docker, PostgreSQL…)")
        self.vocab_edit.setFixedHeight(60)
        lay.addWidget(self.vocab_edit)

        lay.addSpacing(4)
        lay.addWidget(_section("ДИКТОВКА"))
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

        self.overlay_chk = QCheckBox("Индикатор записи внизу экрана")
        self.overlay_chk.setChecked(self.cfg.show_overlay)
        lay.addWidget(self.overlay_chk)

        lay.addSpacing(4)
        lay.addWidget(_section("СИСТЕМА"))
        self.theme_combo = QComboBox()
        for label, val in THEMES:
            self.theme_combo.addItem(label, val)
        self._select_data(self.theme_combo, self.cfg.theme)
        self.theme_combo.currentIndexChanged.connect(self._theme_changed)
        lay.addWidget(_row("Тема", self.theme_combo))

        self.autostart_chk = QCheckBox("Запускать при старте Windows")
        try:
            from reku import autostart
            self.autostart_chk.setChecked(autostart.is_enabled())
        except Exception:
            self.autostart_chk.setEnabled(False)
        self.autostart_chk.toggled.connect(self._autostart_toggled)
        lay.addWidget(self.autostart_chk)

        lay.addSpacing(2)
        self.adv_btn = QPushButton("Дополнительно"); self.adv_btn.setObjectName("LinkBtn")
        self.adv_btn.setCheckable(True); self.adv_btn.setCursor(Qt.PointingHandCursor)
        self.adv_btn.toggled.connect(self._toggle_advanced)
        lay.addWidget(self.adv_btn)

        self.adv_box = QWidget()
        adv = QVBoxLayout(self.adv_box); adv.setContentsMargins(0, 0, 0, 0); adv.setSpacing(8)
        self.compute_combo = QComboBox(); self.compute_combo.addItems(COMPUTES)
        self._select_text(self.compute_combo, self.cfg.compute_type)
        adv.addWidget(_row("Точность", self.compute_combo))
        self.vad_chk = QCheckBox("VAD — резать тишину/шум")
        self.vad_chk.setChecked(self.cfg.vad_filter)
        self.halluc_chk = QCheckBox("Фильтр галлюцинаций")
        self.halluc_chk.setChecked(self.cfg.drop_hallucinations)
        adv.addWidget(self.vad_chk); adv.addWidget(self.halluc_chk)
        prompt_lbl = QLabel("Промпт декодеру"); prompt_lbl.setObjectName("RowLabel")
        adv.addWidget(prompt_lbl)
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlainText(self.cfg.initial_prompt)
        self.prompt_edit.setPlaceholderText(
            "подсказка о стиле/языках диктовки (initial_prompt);\n"
            "влияет на пунктуацию и написание терминов")
        self.prompt_edit.setFixedHeight(76)
        adv.addWidget(self.prompt_edit)
        self.adv_box.setVisible(False)
        lay.addWidget(self.adv_box)
        lay.addStretch(1)

        guard = _WheelGuard(self)
        for combo in inner.findChildren(QComboBox):
            combo.setFocusPolicy(Qt.StrongFocus)   # фокус колесом — тоже нет
            combo.installEventFilter(guard)

        self.settings_scroll = scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        # НЕ зовём scroll.setStyleSheet(...) и НЕ делаем вьюпорт прозрачным: отдельный
        # стиль на контейнере обрывает каскад глобального QSS к виджетам внутри.
        # Прозрачность не нужна — вьюпорт красит palette(Window) = bg_window, что
        # совпадает с карточкой (палитру ставит apply_theme через T.build_palette).
        # полоса прокрутки — чуть левее края карточки: у самого края зона захвата
        # для растягивания окна (gui_resize.BAND_IN) перекрывала бы её ползунок
        wrap = QHBoxLayout(); wrap.setContentsMargins(0, 0, _SCROLL_INSET, 0)
        wrap.addWidget(scroll)
        outer.addLayout(wrap, 1)

        foot = QFrame(); foot.setObjectName("SettingsFooter")
        fl = QVBoxLayout(foot); fl.setContentsMargins(22, 10, 22, 18); fl.setSpacing(6)
        self.runtime_lbl = QLabel("Работает: —")
        self.runtime_lbl.setObjectName("HintLabel")
        fl.addWidget(self.runtime_lbl)
        self.apply_btn = QPushButton("Применить"); self.apply_btn.setObjectName("RecordBtn")
        self.apply_btn.setCursor(Qt.PointingHandCursor)
        self.apply_btn.clicked.connect(self._apply_settings)
        fl.addWidget(self.apply_btn)
        outer.addWidget(foot)
        return page

    def _toggle_advanced(self, on):
        self.adv_box.setVisible(on)
        self._update_adv_icon()
        if on:   # раскрытый блок — сразу в поле зрения
            QTimer.singleShot(0, lambda: self.settings_scroll.ensureWidgetVisible(
                self.prompt_edit, 0, 12))

    def _update_adv_icon(self):
        kind = "chevron_down" if self.adv_btn.isChecked() else "chevron_right"
        self.adv_btn.setIcon(draw_icon(kind, T.ACTIVE.text2, size=14))
        self.adv_btn.setIconSize(QSize(14, 14))

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
        self._clear_hint_error()   # обычная подсказка — сбросить вид/тултип ошибки, если был
        self.hint.setText(f"{key} · {mode}{dev}")

    def _set_hint_error(self, text):
        """Показать текст ошибки в #HintLabel: полностью (перенос строк уже
        включён), с тултипом на случай обрезанной по высоте подсказки, и не
        приглушённым — как обычный hint (стиль — errorState в QSS)."""
        self.hint.setText(text)
        self.hint.setToolTip(text)
        self.hint.setProperty("errorState", "true")
        self.hint.style().unpolish(self.hint); self.hint.style().polish(self.hint)

    def _clear_hint_error(self):
        """Вернуть #HintLabel к обычному приглушённому виду после ошибки."""
        self.hint.setToolTip("")
        self.hint.setProperty("errorState", "false")
        self.hint.style().unpolish(self.hint); self.hint.style().polish(self.hint)

    def _update_runtime_label(self):
        b = getattr(self.engine, "backend", None) if self.engine else None
        if b is None:
            self.runtime_lbl.setText("Работает: —")
            return
        mdl = getattr(b, "model_name", None) or b.name
        self.runtime_lbl.setText(f"Работает: {b.device_label} · {mdl}")

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
        # иконки — рисованные пиксмапы (не шрифт), их цвет не следует за QSS
        # автоматически, поэтому перерисовываем явно под новую палитру
        self.titlebar.update_icons(pal.text2)
        self.gear_btn.setIcon(draw_icon("gear", pal.text2, size=18))
        self.gear_btn.setIconSize(QSize(18, 18))
        self.back_btn.setIcon(draw_icon("back", pal.text2, size=18))
        self.back_btn.setIconSize(QSize(18, 18))
        self._update_adv_icon()
        self.orb.update(); self.wave.update()
        if self._tray_refresh:
            self._tray_refresh(self._state)

    def _theme_changed(self):
        self._sync_cfg_from_disk()   # сохраняем весь конфиг — не затереть правки файла
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
        # error НЕ блокирует кнопку: после «Микрофон не найден» пользователь должен
        # мочь подключить микрофон и повторить запись без перезапуска приложения
        busy = state not in ("idle", "recording", "error")   # loading/downloading/transcribing
        self.rec_btn.setEnabled(not busy)
        err = None
        if state == "idle":
            self._update_hint()          # сама сбрасывает стиль/тултип ошибки
            self._update_runtime_label()
        elif state == "error":
            err = getattr(self.engine, "_last_error", None) if self.engine else None
            err = err or "Не удалось загрузить модель — проверьте устройство/сеть"
            self._set_hint_error(err)
        else:
            # ушли из error в loading/recording/transcribing, минуя idle — стиль
            # подсказки вернуть сразу (текст обновит ближайший идущий в idle/error)
            self._clear_hint_error()
        self.overlay.on_state(state, err)
        if state in ("idle", "error") and self._pending_reload is not None:
            old, self._pending_reload = self._pending_reload, None
            QTimer.singleShot(0, lambda: self._start_reload(old))

    def set_result(self, text):
        # текст уже вставлен в активное окно; в самой программе его не дублируем —
        # показываем лишь короткое подтверждение, что вставка прошла
        self.status.setText("✓ вставлено")
        self._flashing = True
        self._flash_timer.start(1500)
        self.overlay.on_result()

    def _end_flash(self):
        self._flashing = False
        self.status.setText(T.STATE_TEXT.get(self._state, self._state))

    def set_level(self, rms):
        self.orb.set_level(rms)
        self.wave.set_level(rms)
        self.overlay.set_level(rms)

    # ── размер окна: тянется за любой край, размер запоминается ─
    def nativeEvent(self, event_type, message):
        if sys.platform == "win32" and event_type == b"windows_generic_MSG":
            res = gui_resize.handle_native_event(self, self.card.geometry(), message)
            if res is not None:
                return True, res
        return super().nativeEvent(event_type, message)

    def _restore_size(self):
        """Размер, до которого окно растянули в прошлый раз, — в пределах экрана."""
        w = self.cfg.window_width or DEFAULT_SIZE[0]
        h = self.cfg.window_height or DEFAULT_SIZE[1]
        scr = QApplication.primaryScreen()
        if scr is not None:
            g = scr.availableGeometry()
            w, h = min(w, g.width()), min(h, g.height())
        self.resize(max(w, MIN_SIZE[0]), max(h, MIN_SIZE[1]))
        self._saved_size = (self.width(), self.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        timer = getattr(self, "_size_timer", None)
        if timer is not None and self.isVisible():
            timer.start(600)          # сохранить, когда край отпустили

    def _save_size(self):
        size = (self.width(), self.height())
        if size == self._saved_size:
            return
        self._saved_size = size
        from reku import config as _cfg
        # сохраняем весь конфиг — не затереть правки файла; битый файл ради размера
        # окна не трогаем вовсе
        if not self._sync_cfg_from_disk():
            return
        self.cfg.window_width, self.cfg.window_height = size
        _cfg.save(self.cfg)

    # ── действия ─────────────────────────────────────────────
    def _toggle_record(self):
        """Кнопка «Запись»: команда мгновенная и не блокирует GUI-поток — сам
        движок решает, начать запись или (если модель не поднялась) повторить
        попытку загрузки, поэтому свой поток здесь не нужен."""
        if self.engine is None:
            return
        if self._state == "recording":
            self.engine.request_stop()
        else:
            self.engine.request_start()

    def _lang_changed(self):
        self._sync_cfg_from_disk()   # сохраняем весь конфиг — не затереть правки файла
        self.cfg.language = self.lang_combo.currentData()
        from reku import config as _cfg; _cfg.save(self.cfg)
        if self.engine:
            self.engine.apply_config()
        self._update_hint()

    def _sync_cfg_from_disk(self):
        """Перечитать config.json в self.cfg (сам объект сохраняем — на него держат
        ссылки движок и страницы UI). Без этого сохранение настроек из UI писало
        на диск конфиг из памяти целиком и молча затирало внешние правки файла
        (в т.ч. полей, которых в UI нет). Файл битый (правят руками и ошиблись) —
        настройки дефолтами не подменяем: остаётся последняя рабочая версия из памяти.
        -> True, если файл перечитан."""
        from dataclasses import fields
        from reku import config as _cfg
        try:
            fresh = _cfg.load(strict=True)
        except (ValueError, OSError) as e:
            print(f"[config] не перечитал config.json ({e}) — беру настройки из памяти",
                  file=sys.stderr, flush=True)
            return False
        for f in fields(fresh):
            setattr(self.cfg, f.name, getattr(fresh, f.name))
        return True

    def _open_settings(self):
        """Показать настройки, освежив виджеты из config.json: файл могли править
        руками, пока приложение работало, — иначе «Применить» вернёт старые значения."""
        self._sync_cfg_from_disk()
        c = self.cfg
        self._select_text(self.model_combo, c.model)
        self._select_data(self.device_combo, c.device)
        self._select_text(self.compute_combo, c.compute_type)
        self._select_data(self.hotkey_combo, c.hotkey)
        (self.tog_radio if c.mode == "toggle" else self.ptt_radio).setChecked(True)
        self.theme_combo.blockSignals(True)      # не дёргать _theme_changed зря
        self._select_data(self.theme_combo, c.theme)
        self.theme_combo.blockSignals(False)
        self.vad_chk.setChecked(c.vad_filter)
        self.halluc_chk.setChecked(c.drop_hallucinations)
        self.overlay_chk.setChecked(c.show_overlay)
        self.vocab_edit.setPlainText(c.hotwords)
        self.prompt_edit.setPlainText(c.initial_prompt)
        self.stack.setCurrentIndex(1)

    def _apply_settings(self):
        from reku import config as _cfg
        self._sync_cfg_from_disk()   # не затирать внешние правки полей вне UI
        c = self.cfg
        old = (c.model, c.device, c.compute_type)
        c.model = self.model_combo.currentText()
        c.device = self.device_combo.currentData()
        c.compute_type = self.compute_combo.currentText()
        c.hotkey = self.hotkey_combo.currentData()
        c.mode = "toggle" if self.tog_radio.isChecked() else "ptt"
        c.vad_filter = self.vad_chk.isChecked()
        c.drop_hallucinations = self.halluc_chk.isChecked()
        c.show_overlay = self.overlay_chk.isChecked()
        if not c.show_overlay:
            self.overlay.dismiss()
        # многострочный ввод -> чистый список «через запятую» (по строкам и запятым)
        c.hotwords = ", ".join(s.strip() for s in self.vocab_edit.toPlainText().splitlines()
                               if s.strip())
        c.initial_prompt = self.prompt_edit.toPlainText().strip()
        _cfg.save(c)
        if self.engine:
            self.engine.apply_config()
        self._update_hint()
        self._select_data(self.lang_combo, c.language)
        self.stack.setCurrentIndex(0)
        if self.engine and (c.model, c.device, c.compute_type) != old:
            self._start_reload(old)

    def _start_reload(self, old):
        """Перезагрузить модель в фоне. Идёт запись или распознавание — отложить до
        их конца: движок во время записи модель не меняет, а окно и плашка не должны
        показывать «Загрузку» или «Готов» поверх идущей записи."""
        if self.engine is None:
            return
        if self.engine.busy or self._state in ("recording", "transcribing"):
            self._pending_reload = old       # запустит set_state("idle"/"error")
            return
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
            if not self.engine.reload_model():
                # запись началась между кликом и стартом потока: состояние окну
                # пришлёт сам движок, перезагрузку повторим после записи
                self._reloadDeferred.emit(old)
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


def _should_start_minimized(argv) -> bool:
    """--minimized в аргументах командной строки -> при старте не показывать окно,
    только трей (автозапуск при входе в Windows не должен разворачивать окно
    на весь экран каждый раз). Чистая функция от argv — без побочных эффектов,
    чтобы проверять её без QApplication."""
    return "--minimized" in argv


def main():
    import threading
    from reku import config
    from reku.dictate import DictationApp

    # Оставшийся от чужих экспериментов офлайн-флаг HF (в env сеанса или даже
    # в реестре пользователя) ломает первое скачивание модели: «Cannot find an
    # appropriate cached snapshot folder…». huggingface_hub считает офлайном
    # ЛЮБУЮ из двух переменных (constants.py: HF_HUB_OFFLINE or
    # TRANSFORMERS_OFFLINE) — снимаем обе ДО первого его импорта (значение
    # фиксируется при импорте). Приложение само управляет своими моделями
    # (маркер .download_complete в model_store) и в сеть ходит только когда
    # модели реально нет — офлайн-флаг ему лишь вредит.
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)

    if os.environ.get("REKU_SELFTEST") == "1":
        sys.exit(_run_selftest())

    # Windows: свой AppUserModelID, иначе панель задач считает окно «Python»
    # (иконка pythonw вместо нашей) и не связывает его с ярлыком Reku
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Reku")
        except Exception:
            pass
        try:
            # миграция для автозапуска, сохранённого до появления --minimized —
            # иначе старые установки продолжат разворачивать окно при каждом входе
            from reku import autostart
            autostart.ensure_minimized_flag()
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setWindowIcon(make_icon(T.STATE_RGB["idle"]))   # окно/панель задач: наш микрофон
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

    if not _should_start_minimized(sys.argv):
        win.show()
    threading.Thread(target=lambda: _safe_engine_call(engine.start, engine, bridge),
                     daemon=True).start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
