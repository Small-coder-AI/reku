"""Диагностика вставки текста в активное окно. Запуск: python diag_paste.py

Проверяет 3 способа доставки текста, чтобы понять, где рвётся авто-вставка.
GPU не нужен. ВАЖНО: после старта у тебя 5 секунд, чтобы поставить курсор
в целевое поле (лучше всего — открой Блокнот/Notepad и кликни в него).
"""
import time
from pynput.keyboard import Key, Controller, KeyCode
import pyperclip

kb = Controller()


def countdown(title, n=5):
    print(f"\n=== {title} ===", flush=True)
    for i in range(n, 0, -1):
        print(f"  {i}… поставь курсор в целевое поле", flush=True)
        time.sleep(1)


# Тест A — ТОЧНО как сейчас в приложении: Ctrl+V без задержек, 'v' как символ
countdown("Тест A (как в приложении сейчас): вставляю  AAA_paste_111")
pyperclip.copy("AAA_paste_111")
time.sleep(0.05)
kb.press(Key.ctrl); kb.press('v')
kb.release('v'); kb.release(Key.ctrl)
time.sleep(0.6)
print("  -> A выполнен", flush=True)

# Тест B — устойчивый Ctrl+V: явный виртуальный код клавиши V + микро-задержки
countdown("Тест B (устойчивый Ctrl+V): вставляю  BBB_paste_222")
pyperclip.copy("BBB_paste_222")
time.sleep(0.1)
V = KeyCode.from_vk(0x56)          # 0x56 = физическая клавиша 'V'
kb.press(Key.ctrl); time.sleep(0.03)
kb.press(V); time.sleep(0.03)
kb.release(V); time.sleep(0.03)
kb.release(Key.ctrl)
time.sleep(0.6)
print("  -> B выполнен", flush=True)

# Тест C — посимвольный ввод (insert_method='type'), без буфера и без Ctrl+V
countdown("Тест C (посимвольно): печатаю  CCC_type_333")
kb.type("CCC_type_333")
time.sleep(0.6)
print("  -> C выполнен", flush=True)

print("\nГОТОВО. Посмотри, какие строки реально появились в целевом поле:")
print("  A = AAA_paste_111  (текущий способ приложения)")
print("  B = BBB_paste_222  (устойчивый Ctrl+V)")
print("  C = CCC_type_333   (посимвольный ввод)")
