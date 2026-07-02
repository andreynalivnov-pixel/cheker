#!/usr/bin/env python3
"""
Чекер слотов на дистанцию 5 км для события Night_Yaroslavl26 (russiarunning.com)
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime
from typing import List

import requests
from playwright.sync_api import sync_playwright

URL = "https://reg.russiarunning.com/event/Night_Yaroslavl26"

# Якорь: "Бег · 5 км"
ANCHOR_PATTERN = re.compile(r"бег\s*[·\-:]?\s*5\s?(км|km)\b", re.IGNORECASE)

# Паттерн начала СЛЕДУЮЩЕЙ строки с любой другой дистанцией ("Бег · 10 км" и т.п.)
# По нему обрезаем блок статуса чтобы не захватить данные соседней дистанции
NEXT_ROW_PATTERN = re.compile(r"бег\s*[·\-:]\s*\d", re.IGNORECASE)

# Положительный признак
POSITIVE_PATTERN = re.compile(r"осталось\s+\d+\s+мест[оа]?\b", re.IGNORECASE)

# Маркеры недоступности
SOLD_OUT_MARKERS = [
    "нет мест",
    "мест нет",
    "скоро",
    "регистрация закрыта",
    "закрыта регистрация",
    "распродано",
    "лист ожидания",
    "регистрация завершена",
]

CHECK_INTERVAL_SECONDS = 60 * 60
BACK_WINDOW = 100
FORWARD_WINDOW = 300


def fetch_rendered_text(url: str, timeout_ms: int = 30000) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        page.wait_for_timeout(2000)
        text = page.inner_text("body")
        browser.close()
        return text


def find_5km_rows(full_text: str) -> List[dict]:
    noise_indicators = [
        "регистрация", "закрыта", "нет мест", "осталось", "скоро",
        "бесплатно", "₽", "бег ·", "бег·", "распродано", "лист ожидания",
    ]
    rows = []
    for m in ANCHOR_PATTERN.finditer(full_text):
        back_start = max(0, m.start() - BACK_WINDOW)
        forward_end = min(len(full_text), m.end() + FORWARD_WINDOW)

        title_raw = full_text[back_start:m.start()]

        # Берём текст ПОСЛЕ якоря и обрезаем до начала следующей дистанции
        after_anchor = full_text[m.end():forward_end]
        next_row = NEXT_ROW_PATTERN.search(after_anchor)
        if next_row:
            after_anchor = after_anchor[:next_row.start()]

        status_block = full_text[m.start():m.end()] + after_anchor

        title_lines = [l.strip() for l in title_raw.splitlines() if l.strip()]
        clean_lines = [
            l for l in title_lines
            if not any(ind in l.lower() for ind in noise_indicators)
        ]
        title = " ".join(clean_lines[-3:]) if clean_lines else "5 км"

        rows.append({"title": title, "block": status_block})
    return rows


def classify(block: str) -> str:
    lower = block.lower()
    if POSITIVE_PATTERN.search(lower):
        return "available"
    for marker in SOLD_OUT_MARKERS:
        if marker in lower:
            return "unavailable"
    return "unknown"


def notify_telegram(message: str) -> None:
    token = os.environ.get("RR_TG_TOKEN")
    chat_id = os.environ.get("RR_TG_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": message},
            timeout=10,
        )
    except Exception as e:
        print(f"[!] Не удалось отправить уведомление в Telegram: {e}")


STATUS_LABELS = {
    "available": "ЕСТЬ свободные слоты (нашли 'Осталось N мест')",
    "unavailable": "слотов нет / регистрация закрыта / скоро",
    "unknown": "статус НЕ ОПРЕДЕЛЁН (нет известных маркеров рядом - нужна донастройка)",
}


def check_once(debug: bool = False) -> bool:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        text = fetch_rendered_text(URL)
    except Exception as e:
        print(f"[{now}] Ошибка загрузки страницы: {e}")
        return False

    rows = find_5km_rows(text)
    if not rows:
        print(f"[{now}] Не нашли ни одного варианта дистанции 5 км на странице.")
        if debug:
            print("----- Начало текста страницы (первые 3000 символов) -----")
            print(text[:3000])
        return False

    any_available = False
    for row in rows:
        result = classify(row["block"])
        if debug:
            print(f"[{now}] Вариант '{row['title']}', фрагмент:\n---\n{row['block']}\n---")
        print(f"[{now}] Вариант '{row['title']}': {STATUS_LABELS[result]}")
        if result == "available":
            any_available = True
            notify_telegram(
                f"Похоже открылась регистрация: «{row['title']}» на странице {URL}!"
            )

    return any_available


def main():
    parser = argparse.ArgumentParser(description="Чекер слотов на 5 км Night_Yaroslavl26")
    parser.add_argument("--debug", action="store_true", help="Подробный вывод")
    parser.add_argument("--loop", action="store_true", help="Бесконечный цикл")
    parser.add_argument("--interval", type=int, default=CHECK_INTERVAL_SECONDS)
    args = parser.parse_args()

    if not args.loop:
        check_once(debug=args.debug)
        return

    print(f"Запускаю мониторинг, интервал {args.interval} сек. Остановка - Ctrl+C.")
    while True:
        try:
            check_once(debug=args.debug)
        except KeyboardInterrupt:
            print("Остановлено пользователем.")
            sys.exit(0)
        except Exception as e:
            print(f"Непредвиденная ошибка: {e}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
