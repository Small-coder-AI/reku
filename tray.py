"""Трей-иконка для whisper_ptt. Лёгкий нативный индикатор + меню.

Запуск (с иконкой в трее, без консоли):
    pythonw.exe tray.py
Для отладки (видно консоль + трей):
    python tray.py

Цвет иконки = статус: серый — загрузка, синий — готов,
красный — идёт запись, оранжевый — распознаю.
Меню: режим (PTT/Toggle), язык (авто/ru/en), выход.
Смена режима/языка пишется в config.json и применяется сразу (без перезагрузки модели).
"""
import threading

import pystray
from PIL import Image, ImageDraw

import config
from dictate import DictationApp

_COLORS = {
    "loading":      (150, 150, 150),
    "idle":         (70, 130, 180),
    "recording":    (220, 50, 50),
    "transcribing": (230, 150, 30),
}
_TITLES = {
    "loading":      "whisper_ptt: загрузка модели…",
    "idle":         "whisper_ptt: готов",
    "recording":    "whisper_ptt: ● запись…",
    "transcribing": "whisper_ptt: ⏳ распознаю…",
}


def _make_image(color) -> Image.Image:
    """Иконка-микрофон в кружке заданного цвета."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, 58, 58), fill=color)
    white = (255, 255, 255)
    d.rounded_rectangle((28, 18, 36, 36), radius=4, fill=white)  # капсула микрофона
    d.arc((24, 28, 40, 44), 0, 180, fill=white, width=3)         # дужка
    d.line((32, 44, 32, 50), fill=white, width=3)                # ножка
    d.line((26, 50, 38, 50), fill=white, width=3)                # подставка
    return img


_IMAGES = {k: _make_image(c) for k, c in _COLORS.items()}


def build_icon(cfg: config.Config):
    """Собирает (app, icon). run() не вызывается — удобно для тестов сборки."""
    state_box = {"icon": None}

    def on_state(state):
        ic = state_box["icon"]
        if ic is not None:
            ic.icon = _IMAGES.get(state, _IMAGES["idle"])
            ic.title = _TITLES.get(state, "whisper_ptt")

    app = DictationApp(cfg, on_state=on_state)

    def set_mode(m):
        def handler(icon, item):
            cfg.mode = m
            config.save(cfg)
        return handler

    def set_lang(lang):
        def handler(icon, item):
            cfg.language = lang
            config.save(cfg)
        return handler

    def quit_app(icon, item):
        app.stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("PTT (зажим)", set_mode("ptt"),
                         checked=lambda i: cfg.mode == "ptt", radio=True),
        pystray.MenuItem("Toggle (вкл/выкл)", set_mode("toggle"),
                         checked=lambda i: cfg.mode == "toggle", radio=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Язык: авто", set_lang(""),
                         checked=lambda i: cfg.language == "", radio=True),
        pystray.MenuItem("Язык: ru", set_lang("ru"),
                         checked=lambda i: cfg.language == "ru", radio=True),
        pystray.MenuItem("Язык: en", set_lang("en"),
                         checked=lambda i: cfg.language == "en", radio=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", quit_app),
    )
    icon = pystray.Icon("whisper_ptt", _IMAGES["loading"], _TITLES["loading"], menu)
    state_box["icon"] = icon
    return app, icon


def main():
    cfg = config.load()
    app, icon = build_icon(cfg)

    def setup(icon):
        icon.visible = True
        # грузим модель и стартуем слушатель в фоне — иконка появляется сразу
        threading.Thread(target=app.start, daemon=True).start()

    icon.run(setup=setup)


if __name__ == "__main__":
    main()
