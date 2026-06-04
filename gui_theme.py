"""Тёмная тема whisper_ptt: палитра + QSS. Один источник правды по цветам."""

# ── палитра (cool-dark, синий бренд-акцент) ──────────────────
BG_WINDOW   = "#0F1115"   # фон окна (почти чёрный с синевой)
BG_CARD     = "#171A21"   # карточки/панели
BG_CARD_2   = "#1E222B"   # вложенные элементы, поля
BG_HOVER    = "#252A34"
BORDER      = "#2A2F3A"
BORDER_SOFT = "#21252E"

TEXT        = "#E8EAED"
TEXT_2      = "#9AA0AC"
TEXT_DIM    = "#6B7280"

ACCENT      = "#4C8DFF"   # idle / бренд (синий)
ACCENT_REC  = "#FF4D5E"   # запись (красный)
ACCENT_BUSY = "#FFB020"   # распознавание (янтарный)
ACCENT_OK   = "#38D39F"   # успех (зелёный)

# RGB-кортежи для рисования (QPainter)
def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

RGB = {k: _rgb(v) for k, v in dict(
    bg=BG_WINDOW, card=BG_CARD, card2=BG_CARD_2, border=BORDER,
    text=TEXT, text2=TEXT_2, dim=TEXT_DIM,
    accent=ACCENT, rec=ACCENT_REC, busy=ACCENT_BUSY, ok=ACCENT_OK,
).items()}

# состояние -> цвет акцента orb'а
STATE_RGB = {
    "loading":      RGB["dim"],
    "idle":         RGB["accent"],
    "recording":    RGB["rec"],
    "transcribing": RGB["busy"],
}
STATE_TEXT = {
    "loading":      "Загрузка модели…",
    "idle":         "Готов",
    "recording":    "Запись…",
    "transcribing": "Распознаю…",
}

QSS = f"""
#Card {{
    background: {BG_WINDOW};
    border: 1px solid {BORDER};
    border-radius: 16px;
}}
QWidget {{
    color: {TEXT};
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}}
#TitleLabel {{ color: {TEXT}; font-size: 13px; font-weight: 600; letter-spacing: 0.3px; }}
#StatusLabel {{ color: {TEXT_2}; font-size: 15px; font-weight: 500; }}
#HintLabel  {{ color: {TEXT_DIM}; font-size: 11px; }}
#SectionLabel {{ color: {TEXT_DIM}; font-size: 11px; font-weight: 600; letter-spacing: 0.8px; }}

#TextCard {{
    background: {BG_CARD};
    border: 1px solid {BORDER_SOFT};
    border-radius: 12px;
}}
#TextView {{
    background: transparent; border: none;
    color: {TEXT}; font-size: 14px; line-height: 1.4;
}}

/* кнопки заголовка (min/close) */
#WinBtn {{ background: transparent; border: none; border-radius: 6px;
           color: {TEXT_2}; font-size: 14px; padding: 0; }}
#WinBtn:hover {{ background: {BG_HOVER}; color: {TEXT}; }}
#CloseBtn:hover {{ background: {ACCENT_REC}; color: white; }}

/* первичная кнопка записи */
#RecordBtn {{
    background: {ACCENT}; color: white; border: none;
    border-radius: 10px; font-size: 13px; font-weight: 600; padding: 9px 16px;
}}
#RecordBtn:hover {{ background: #5C9AFF; }}
#RecordBtn:pressed {{ background: #3D7AE6; }}
#RecordBtn[recording="true"] {{ background: {ACCENT_REC}; }}
#RecordBtn[recording="true"]:hover {{ background: #FF6373; }}

/* иконочные кнопки (шестерёнка, копировать, назад) */
#IconBtn {{ background: {BG_CARD_2}; border: 1px solid {BORDER}; border-radius: 10px;
            color: {TEXT_2}; font-size: 15px; }}
#IconBtn:hover {{ background: {BG_HOVER}; color: {TEXT}; }}

QComboBox {{
    background: {BG_CARD_2}; border: 1px solid {BORDER}; border-radius: 9px;
    padding: 6px 10px; color: {TEXT}; min-height: 18px;
}}
QComboBox:hover {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {BG_CARD_2}; border: 1px solid {BORDER}; border-radius: 8px;
    selection-background-color: {ACCENT}; outline: none; padding: 4px;
}}
QLineEdit {{
    background: {BG_CARD_2}; border: 1px solid {BORDER}; border-radius: 9px;
    padding: 7px 10px; color: {TEXT}; selection-background-color: {ACCENT};
}}
QLineEdit:focus {{ border-color: {ACCENT}; }}

QCheckBox {{ color: {TEXT_2}; spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid {BORDER}; background: {BG_CARD_2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT};
    image: none; }}
QRadioButton {{ color: {TEXT_2}; spacing: 8px; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 8px;
    border: 1px solid {BORDER}; background: {BG_CARD_2}; }}
QRadioButton::indicator:checked {{ background: {ACCENT}; border: 4px solid {BG_CARD_2}; }}

QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""
