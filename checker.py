#!/usr/bin/env python3
"""
Чекер слотов на дистанцию 5 км для события Night_Yaroslavl26 (russiarunning.com)

Страница регистрации - это JS-приложение (SPA), обычный HTTP-запрос отдаёт
пустой каркас без данных. Поэтому скрипт использует Playwright (headless
Chromium), который полностью отрисовывает страницу, как настоящий браузер.

УСТАНОВКА:
    pip install playwright requests
    playwright install chromium

ИСПОЛЬЗОВАНИЕ:
    # Разовая проверка с подробным выводом (чтобы подобрать ключевые слова
    # под реальную верстку сайта - см. примечание ниже):
    python checker.py --debug

    # Разовая проверка без отладочного вывода (удобно для cron):
    python checker.py

    # Бесконечный цикл, проверка каждый час:
    python checker.py --loop

УВЕДОМЛЕНИЯ В TELEGRAM (опционально):
    1. Создайте бота через @BotFather, получите TOKEN.
    2. Узнайте свой chat_id, например через @userinfobot.
    3. Задайте переменные окружения перед запуском:
        export RR_TG_TOKEN="ваш_токен"
        export RR_TG_CHAT_ID="ваш_chat_id"

ВАЖНОЕ ПРИМЕЧАНИЕ:
    Я не смог напрямую "прощупать" живую вёрстку сайта из своей среды
    (нет доступа к этому домену), поэтому слова-маркеры ("мест нет",
    "регистрация закрыта" и т.п.) - это эвристика. Запустите сначала
    `python checker.py --debug` и посмотрите, что реально находится в
    блоке про "5 км" - если формулировки на сайте другие, поправьте
    список SOLD_OUT_MARKERS ниже.
"""

import argparse
import os
import sys
import time
from datetime import datetime
from typing import Optional

import requests
from playwright.sync_api import sync_playwright

URL = "https://reg.russiarunning.com/event/Night_Yaroslavl26"

# Варианты написания дистанции на странице
DISTANCE_KEYWORDS = ["5 км", "5км", "5 km", "5KM", "5 KM"]

# Слова-маркеры того, что слотов НЕТ (если не нашли - считаем, что слоты есть)
SOLD_OUT_MARKERS = [
    "мест нет",
    "регистрация закрыта",
    "распродано",
    "закрыта регистрация",
    "лист ожидания",
    "нет свободных мест",
    "регистрация завершена",
]

CHECK_INTERVAL_SECONDS = 60 * 60  # раз в час


def fetch_rendered_text(url: str, timeout_ms: int = 30000) -> str:
    """Открывает страницу в headless-браузере и возвращает видимый текст body."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        page.wait_for_timeout(2000)  # доп. время на отрисовку SPA
        text = page.inner_text("body")
        browser.close()
        return text


def extract_distance_block(full_text: str, keyword: str, window: int = 500) -> Optional[str]:
    """Вырезает кусок текста вокруг первого упоминания дистанции."""
    idx = full_text.lower().find(keyword.lower())
    if idx == -1:
        return None
    start = max(0, idx - window // 4)
    end = min(len(full_text), idx + window)
    return full_text[start:end]


def find_5km_block(full_text: str) -> Optional[str]:
    for kw in DISTANCE_KEYWORDS:
        block = extract_distance_block(full_text, kw)
        if block:
            return block
    return None


def is_available(block: str) -> bool:
    lower = block.lower()
    return not any(marker in lower for marker in SOLD_OUT_MARKERS)


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


def check_once(debug: bool = False) -> bool:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        text = fetch_rendered_text(URL)
    except Exception as e:
        print(f"[{now}] Ошибка загрузки страницы: {e}")
        return False

    block = find_5km_block(text)
    if block is None:
        print(f"[{now}] Не нашли упоминание дистанции 5 км на странице.")
        if debug:
            print("----- Начало текста страницы (для отладки, первые 3000 символов) -----")
            print(text[:3000])
        return False

    if debug:
        print(f"[{now}] Найденный фрагмент про 5 км:\n---\n{block}\n---")

    available = is_available(block)
    status = "ЕСТЬ свободные слоты (предположительно)" if available else "слотов нет / регистрация закрыта"
    print(f"[{now}] Дистанция 5 км: {status}")

    if available:
        notify_telegram(
            f"На странице {URL} похоже появились слоты на 5 км! Проверьте: {URL}"
        )
    return available


def main():
    parser = argparse.ArgumentParser(description="Чекер слотов на 5 км Night_Yaroslavl26")
    parser.add_argument("--debug", action="store_true", help="Подробный вывод для настройки ключевых слов")
    parser.add_argument("--loop", action="store_true", help="Бесконечный цикл с проверкой каждый час")
    parser.add_argument("--interval", type=int, default=CHECK_INTERVAL_SECONDS, help="Интервал в секундах (по умолчанию 3600)")
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
