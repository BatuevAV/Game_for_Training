#!/usr/bin/env python3
"""
Скрипт для обновления статуса Premium у пользователя.

Использование:
    python update_premium.py <telegram_id> <true|false>

Пример:
    python update_premium.py 12345 true
    python update_premium.py 12345 false
"""

import sys
import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

from testik.db import SessionLocal, UserDB


def update_premium_status(telegram_id: int, is_premium: bool) -> None:
    """Обновить статус Premium для пользователя по telegram_id."""
    if not SessionLocal:
        print("❌ База данных не настроена. Проверьте DATABASE_URL в .env")
        return

    with SessionLocal() as session:
        user = (
            session.query(UserDB)
            .filter(UserDB.telegram_id == telegram_id)
            .one_or_none()
        )

        if not user:
            print(f"❌ Пользователь с telegram_id={telegram_id} не найден")
            return

        old_status = user.is_premium
        user.is_premium = is_premium
        session.commit()

        status_emoji = "✅" if is_premium else "❌"
        print(f"\n{status_emoji} Статус Premium обновлён для пользователя:")
        print(f"   ID: {user.id}")
        print(f"   Telegram ID: {user.telegram_id}")
        print(f"   Username: {user.username or 'N/A'}")
        print(f"   Было: {'Premium' if old_status else 'Free'}")
        print(f"   Стало: {'Premium' if is_premium else 'Free'}")


def main():
    if len(sys.argv) != 3:
        print("Использование: python update_premium.py <telegram_id> <true|false>")
        print("\nПример:")
        print("  python update_premium.py 12345 true   # Включить Premium")
        print("  python update_premium.py 12345 false  # Отключить Premium")
        sys.exit(1)

    try:
        telegram_id = int(sys.argv[1])
    except ValueError:
        print("❌ Ошибка: telegram_id должен быть числом")
        sys.exit(1)

    premium_str = sys.argv[2].lower()
    if premium_str not in ("true", "false", "1", "0", "yes", "no"):
        print("❌ Ошибка: второй аргумент должен быть true или false")
        sys.exit(1)

    is_premium = premium_str in ("true", "1", "yes")

    update_premium_status(telegram_id, is_premium)


if __name__ == "__main__":
    main()
