"""Генерирует app.ico из gui.make_icon() — переиспользует существующую отрисовку
иконки (кружок + микрофон). Запуск из venv: python make_ico.py

Сохраняем несколько размеров в один .ico (Windows подберёт нужный для трея/панели).
QIcon уже умеет рендерить QPixmap нужного размера через make_icon(rgb).
"""
import os


def build(out="app.ico"):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QImage
    import gui
    import gui_theme as T

    from PySide6.QtCore import QBuffer, QByteArray
    app = QApplication.instance() or QApplication([])  # нужен для QPixmap
    icon = gui.make_icon(T.STATE_RGB.get("idle", (90, 200, 250)))

    # make_icon рисует в 64px — берём этот нативный (самый чёткий) кадр как источник
    img = icon.pixmap(QSize(64, 64)).toImage().convertToFormat(QImage.Format_RGBA8888)

    # Многоразмерный .ico (чёткая даунскейл-пирамида) через Pillow — он есть в dev-venv.
    # Pillow исключён из .exe, но make_ico.py гоняется ДО PyInstaller, так что ок.
    try:
        import io
        from PIL import Image
        ba = QByteArray(); buf = QBuffer(ba); buf.open(QBuffer.WriteOnly)
        img.save(buf, "PNG"); buf.close()
        pil = Image.open(io.BytesIO(bytes(ba))).convert("RGBA")
        pil.save(out, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)])
        ok = True
    except Exception as e:                       # фолбэк: одиночный кадр средствами Qt
        print(f"[make_ico] Pillow недоступен ({e}); пишу одиночный кадр Qt")
        ok = img.save(out, "ICO")
    print(f"{'OK' if ok else 'FAIL'}: {os.path.abspath(out)}")
    return ok


if __name__ == "__main__":
    build()
