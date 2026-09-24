"""Растягивание frameless-окна за любой край и угол, как у обычных окон Windows.

У окна без системной рамки Windows не знает, где края, пока окно не ответит на
WM_NCHITTEST кодом края (HTLEFT, HTBOTTOMRIGHT…). Дальше всё делает система:
курсор-стрелка, само растягивание, минимальный размер (его Qt сообщает через
WM_GETMINMAXINFO). Зона захвата — полоса вдоль видимой карточки: чуть снаружи,
в поле тени (как невидимая рамка у окон Windows 11), и чуть внутри.
"""
import ctypes
from ctypes import wintypes

BAND_OUT = 8     # px снаружи карточки, в поле тени
BAND_IN = 4      # px внутри карточки — не мешает кнопкам и полям у края
CORNER = 16      # px от угла, где тянется по диагонали (угол карточки скруглён)

WM_SETCURSOR = 0x0020
WM_NCHITTEST = 0x0084

# (по горизонтали, по вертикали): -1 — левый/верхний край, 1 — правый/нижний
_HITTEST = {
    (-1, 0): 10, (1, 0): 11, (0, -1): 12, (-1, -1): 13,   # HTLEFT HTRIGHT HTTOP HTTOPLEFT
    (1, -1): 14, (0, 1): 15, (-1, 1): 16, (1, 1): 17,     # HTTOPRIGHT HTBOTTOM HTBOTTOMLEFT HTBOTTOMRIGHT
}
_IDC_SIZENWSE, _IDC_SIZENESW, _IDC_SIZEWE, _IDC_SIZENS = 32642, 32643, 32644, 32645
_CURSOR = {10: _IDC_SIZEWE, 11: _IDC_SIZEWE, 12: _IDC_SIZENS, 15: _IDC_SIZENS,
           13: _IDC_SIZENWSE, 17: _IDC_SIZENWSE, 14: _IDC_SIZENESW, 16: _IDC_SIZENESW}


def edge_at(x, y, left, top, right, bottom):
    """Край карточки под точкой (x, y) в координатах окна: пара (h, v) из -1/0/1,
    (0, 0) — не край. Чистая функция — проверяется без Windows."""
    if not (left - BAND_OUT <= x <= right + BAND_OUT
            and top - BAND_OUT <= y <= bottom + BAND_OUT):
        return 0, 0
    near_l, near_r = x <= left + BAND_IN, x >= right - BAND_IN
    near_t, near_b = y <= top + BAND_IN, y >= bottom - BAND_IN
    # у угла зона шире вдоль обоих краёв: за скруглённый угол хватать удобно
    by_l, by_r = x <= left + CORNER, x >= right - CORNER
    by_t, by_b = y <= top + CORNER, y >= bottom - CORNER
    on_h_edge, on_v_edge = near_l or near_r, near_t or near_b
    h = -1 if near_l or (by_l and on_v_edge) else 1 if near_r or (by_r and on_v_edge) else 0
    v = -1 if near_t or (by_t and on_h_edge) else 1 if near_b or (by_b and on_h_edge) else 0
    return h, v


_user32 = None


def _api():
    """Свой экземпляр user32 с argtypes: общий ctypes.windll.user32 не трогаем —
    его функции делят с нами pynput и другие модули."""
    global _user32
    if _user32 is None:
        u = ctypes.WinDLL("user32")
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetWindowRect.restype = wintypes.BOOL
        u.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
        u.LoadCursorW.restype = wintypes.HANDLE
        u.SetCursor.argtypes = [wintypes.HANDLE]
        u.SetCursor.restype = wintypes.HANDLE
        _user32 = u
    return _user32


def handle_native_event(win, card, message):
    """Обработать сообщение Windows для окна win с карточкой card (QRect в
    координатах окна). Возвращает LRESULT, если сообщение наше, иначе None."""
    msg = wintypes.MSG.from_address(int(message))
    if msg.message == WM_NCHITTEST:
        if win.isMaximized() or win.isFullScreen():
            return None
        u = _api()
        rc = wintypes.RECT()
        if not u.GetWindowRect(msg.hWnd, ctypes.byref(rc)):
            return None
        # экранные координаты в физических пикселях, со знаком (мониторы левее/выше
        # основного дают отрицательные); окно Qt меряет в логических
        x = ctypes.c_short(msg.lParam & 0xFFFF).value
        y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
        dpr = win.devicePixelRatioF() or 1.0
        h, v = edge_at((x - rc.left) / dpr, (y - rc.top) / dpr,
                       card.left(), card.top(), card.right(), card.bottom())
        return _HITTEST.get((h, v))
    if msg.message == WM_SETCURSOR:
        # курсор-стрелку ставим сами: Qt на WM_SETCURSOR ставит курсор виджета
        cursor = _CURSOR.get(msg.lParam & 0xFFFF)
        if cursor is not None:
            u = _api()
            u.SetCursor(u.LoadCursorW(None, cursor))
            return 1
    return None
