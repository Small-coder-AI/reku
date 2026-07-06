"""Темы Reku: палитры (тёмная/светлая) + QSS. Один источник правды по цветам.

Тема выбирается в config.theme: 'system' | 'dark' | 'light'. 'system' следует теме
Windows через QStyleHints.colorScheme(). Смена темы в рантайме: set_active_theme(pal)
МУТИРУЕТ словари RGB/STATE_RGB на месте (их по ссылке читают gui_widgets в paintEvent),
build_qss(pal) пересобирает стиль. Применение — в MainWindow.apply_theme (gui.py).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str
    bg_window: str
    bg_card: str
    bg_card2: str
    bg_hover: str
    border: str
    border_soft: str
    text: str
    text2: str
    text_dim: str
    accent: str
    accent_hover: str
    accent_pressed: str
    rec: str
    rec_hover: str
    busy: str
    ok: str


# ── тёмная (исходная cool-dark, синий бренд-акцент) ──────────
DARK = Palette(
    name="dark",
    bg_window="#0F1115", bg_card="#171A21", bg_card2="#1E222B", bg_hover="#252A34",
    border="#2A2F3A", border_soft="#21252E",
    text="#E8EAED", text2="#9AA0AC", text_dim="#6B7280",
    accent="#4C8DFF", accent_hover="#5C9AFF", accent_pressed="#3D7AE6",
    rec="#FF4D5E", rec_hover="#FF6373", busy="#FFB020", ok="#38D39F",
)

# ── светлая (гармония с брендовым синим; контраст выверен под читаемость на белом) ──
LIGHT = Palette(
    name="light",
    bg_window="#EEF1F7", bg_card="#FFFFFF", bg_card2="#F0F3F8", bg_hover="#E1E7F1",
    border="#C8D2E0", border_soft="#DDE4EE",
    text="#171B24", text2="#3F4856", text_dim="#5C6675",   # темнее -> метки/заголовки видны
    accent="#2F6FE0", accent_hover="#4683EC", accent_pressed="#2257BE",
    rec="#E23744", rec_hover="#F0505D", busy="#D9820B", ok="#159B72",
)

PALETTES = {"dark": DARK, "light": LIGHT}


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


# ── динамические структуры (МУТИРУЮТСЯ на месте при смене темы) ──────────
ACTIVE = DARK                 # текущая палитра
RGB = {}                      # имя -> (r,g,b); читается по ссылке в paintEvent виджетов
STATE_RGB = {}                # состояние -> (r,g,b)
STATE_TEXT = {
    "loading":      "Загрузка модели…",
    "downloading":  "Скачиваю модель…",
    "idle":         "Готов",
    "recording":    "Запись…",
    "transcribing": "Распознаю…",
    "error":        "Ошибка",
}

# строковые алиасы для обратной совместимости (обновляются в _populate)
ACCENT = DARK.accent
TEXT = DARK.text
TEXT_2 = DARK.text2


def _populate(pal: Palette):
    """Заполняет RGB/STATE_RGB из палитры, МУТИРУЯ существующие dict (их идентичность
    сохраняется — gui_widgets читают эти же объекты по ссылке)."""
    global ACTIVE, ACCENT, TEXT, TEXT_2
    ACTIVE = pal
    RGB.clear()
    RGB.update(
        bg=_rgb(pal.bg_window), card=_rgb(pal.bg_card), card2=_rgb(pal.bg_card2),
        border=_rgb(pal.border), text=_rgb(pal.text), text2=_rgb(pal.text2),
        dim=_rgb(pal.text_dim), accent=_rgb(pal.accent), rec=_rgb(pal.rec),
        busy=_rgb(pal.busy), ok=_rgb(pal.ok),
    )
    STATE_RGB.clear()
    STATE_RGB.update(
        loading=RGB["dim"], downloading=RGB["busy"], idle=RGB["accent"],
        recording=RGB["rec"], transcribing=RGB["busy"], error=RGB["rec"],
    )
    ACCENT, TEXT, TEXT_2 = pal.accent, pal.text, pal.text2


def build_qss(p: Palette, check_url=None) -> str:
    """Полный QSS из палитры. Цвета только из полей p — для светлой/тёмной идентично.
    check_url (если задан) — путь к PNG-галочке для индикатора включённого чекбокса."""
    check_rule = f"image: url({check_url});" if check_url else "image: none;"
    return f"""
#Card {{ background: {p.bg_window}; border: 1px solid {p.border}; border-radius: 16px; }}
/* фон страницы настроек — ЯВНО в общем QSS (надёжнее palette(Window), который к
   моменту первого показа мог не примениться к вьюпорту скролла); цвет = карточка */
#SettingsInner {{ background: {p.bg_window}; }}
QWidget {{ color: {p.text}; font-family: 'Segoe UI', sans-serif; font-size: 13px; }}
#TitleLabel {{ color: {p.text}; font-size: 13px; font-weight: 600; letter-spacing: 0.3px; }}
#StatusLabel {{ color: {p.text2}; font-size: 15px; font-weight: 500; }}
#HintLabel  {{ color: {p.text_dim}; font-size: 11px; }}
#SectionLabel {{ color: {p.text_dim}; font-size: 11px; font-weight: 600; letter-spacing: 0.8px; }}
#RowLabel {{ color: {p.text2}; }}

/* кнопки заголовка (min/close) */
#WinBtn {{ background: transparent; border: none; border-radius: 6px;
           color: {p.text2}; font-size: 14px; padding: 0; }}
#WinBtn:hover {{ background: {p.bg_hover}; color: {p.text}; }}
#CloseBtn:hover {{ background: {p.rec}; color: white; }}

/* первичная кнопка записи */
#RecordBtn {{ background: {p.accent}; color: white; border: none;
             border-radius: 10px; font-size: 13px; font-weight: 600; padding: 9px 16px; }}
#RecordBtn:hover {{ background: {p.accent_hover}; }}
#RecordBtn:pressed {{ background: {p.accent_pressed}; }}
#RecordBtn[recording="true"] {{ background: {p.rec}; }}
#RecordBtn[recording="true"]:hover {{ background: {p.rec_hover}; }}
#RecordBtn:disabled {{ background: {p.bg_hover}; color: {p.text_dim}; }}

/* иконочные кнопки (шестерёнка, копировать, назад) */
#IconBtn {{ background: {p.bg_card2}; border: 1px solid {p.border}; border-radius: 10px;
            color: {p.text2}; font-size: 15px; }}
#IconBtn:hover {{ background: {p.bg_hover}; color: {p.text}; }}

QComboBox {{ background: {p.bg_card2}; border: 1px solid {p.border}; border-radius: 9px;
             padding: 6px 10px; color: {p.text}; min-height: 18px; }}
QComboBox:hover {{ border-color: {p.accent}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
/* всплывающий список: фон/цвет/выделение заданы ЯВНО — иначе нативный стиль Windows
   рисует его системной (часто тёмной) палитрой, и в светлой теме он нечитаем */
QComboBox QAbstractItemView {{ background: {p.bg_card}; color: {p.text};
    border: 1px solid {p.border}; border-radius: 8px;
    selection-background-color: {p.accent}; selection-color: #FFFFFF;
    outline: none; padding: 4px; }}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 3px 8px; color: {p.text}; }}
QComboBox QAbstractItemView::item:selected {{ background: {p.accent}; color: #FFFFFF; }}
QComboBox QAbstractItemView::item:disabled {{ color: {p.text_dim}; }}

QLineEdit {{ background: {p.bg_card2}; border: 1px solid {p.border}; border-radius: 9px;
             padding: 7px 10px; color: {p.text}; selection-background-color: {p.accent}; }}
QLineEdit:focus {{ border-color: {p.accent}; }}
QPlainTextEdit, QTextEdit {{ background: {p.bg_card2}; border: 1px solid {p.border};
    border-radius: 9px; padding: 6px 8px; color: {p.text};
    selection-background-color: {p.accent}; }}
QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {p.accent}; }}

/* чекбокс: включённый — синий квадрат с БЕЛОЙ ГАЛОЧКОЙ (а не просто заливка),
   чтобы выбор читался однозначно */
QCheckBox {{ color: {p.text2}; spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid {p.border}; background: {p.bg_card2}; }}
QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; {check_rule} }}
/* радио: включённое — кольцо с ТОЧКОЙ в центре (radial-gradient, без картинки) */
QRadioButton {{ color: {p.text2}; spacing: 8px; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 8px;
    border: 1px solid {p.border}; background: {p.bg_card2}; }}
QRadioButton::indicator:hover {{ border-color: {p.accent}; }}
QRadioButton::indicator:checked {{ border: 1px solid {p.accent};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {p.accent}, stop:0.45 {p.accent}, stop:0.5 {p.bg_card2}, stop:1 {p.bg_card2}); }}

QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {p.text_dim}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


def resolve_theme(choice: str, app=None) -> Palette:
    """choice 'dark'/'light' -> прямо; 'system' (или незнакомое) -> по теме Windows
    через QStyleHints.colorScheme(). Любой сбой -> DARK (исходный вид)."""
    if choice in PALETTES:
        return PALETTES[choice]
    try:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import Qt
        app = app or QGuiApplication.instance()
        scheme = app.styleHints().colorScheme()
        return LIGHT if scheme == Qt.ColorScheme.Light else DARK
    except Exception:
        return DARK


def set_active_theme(pal: Palette, check_url=None) -> str:
    """Сделать палитру активной (мутирует RGB/STATE_RGB на месте) и вернуть её QSS."""
    _populate(pal)
    return build_qss(pal, check_url)


def build_palette(p: Palette):
    """QPalette из палитры — для нативных частей, которые QSS не перекрывает (рамка
    всплывающего списка комбобокса, тултипы). Без неё в светлой теме всплывашка может
    взять тёмную системную палитру Windows и стать нечитаемой. Импорт Qt — лениво,
    чтобы модуль оставался импортируемым без QApplication (его читают headless-тесты)."""
    from PySide6.QtGui import QPalette, QColor
    role, grp = QPalette.ColorRole, QPalette.ColorGroup
    pal = QPalette()
    pal.setColor(role.Window, QColor(p.bg_window))
    pal.setColor(role.WindowText, QColor(p.text))
    pal.setColor(role.Base, QColor(p.bg_card))
    pal.setColor(role.AlternateBase, QColor(p.bg_card2))
    pal.setColor(role.Text, QColor(p.text))
    pal.setColor(role.Button, QColor(p.bg_card2))
    pal.setColor(role.ButtonText, QColor(p.text))
    pal.setColor(role.ToolTipBase, QColor(p.bg_card))
    pal.setColor(role.ToolTipText, QColor(p.text))
    pal.setColor(role.Highlight, QColor(p.accent))
    pal.setColor(role.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(role.PlaceholderText, QColor(p.text_dim))
    for r in (role.Text, role.WindowText, role.ButtonText):
        pal.setColor(grp.Disabled, r, QColor(p.text_dim))
    return pal


# по умолчанию — тёмная, пока приложение не применит выбор из конфига
_populate(DARK)
