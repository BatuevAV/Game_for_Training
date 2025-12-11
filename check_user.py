#!/usr/bin/env python3
"""
Скрипт для просмотра информации о пользователе.

Использование:
    python check_user.py <telegram_id>

Пример:
    python check_user.py 12345
"""

import sys
from datetime import date, datetime
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

from testik.db import SessionLocal, UserDB, SkillStatsDB, GameSessionDB


def check_user(telegram_id: int) -> None:
    """Показать информацию о пользователе по telegram_id."""
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

        # Получаем статистику навыков
        stats = session.get(SkillStatsDB, user.id)

        # Подсчитываем игры за сегодня
        today = date.today()
        since_dt = datetime.combine(today, datetime.min.time())
        games_today = (
            session.query(GameSessionDB)
            .filter(
                GameSessionDB.user_id == user.id,
                GameSessionDB.started_at >= since_dt,
            )
            .count()
        )

        # Выводим информацию
        status_emoji = "⭐" if user.is_premium else "🆓"
        print(f"\n{status_emoji} Информация о пользователе:")
        print(f"{'='*60}")
        print(f"ID в базе:       {user.id}")
        print(f"Telegram ID:     {user.telegram_id}")
        print(f"Username:        {user.username or 'N/A'}")
        print(f"Статус:          {'Premium ⭐' if user.is_premium else 'Free 🆓'}")
        print(f"Зарегистрирован: {user.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Последняя актив: {user.last_active_at.strftime('%Y-%m-%d %H:%M:%S')}")

        if stats:
            print(f"\n📊 Навыки:")
            print(f"  Память:   Уровень {stats.memory_level} (XP: {stats.memory_xp})")
            print(f"  Реакция:  Уровень {stats.reaction_level} (XP: {stats.reaction_xp})")
            print(f"  Серия:    {stats.daily_streak} дней")
            if stats.last_training_date:
                print(f"  Последняя тренировка: {stats.last_training_date}")

        print(f"\n🎮 Игры:")
        print(f"  Сегодня сыграно: {games_today}")
        if not user.is_premium:
            print(f"  Лимит: 8 игр/день")
            remaining = max(0, 8 - games_today)
            print(f"  Осталось: {remaining} игр")
        else:
            print(f"  Лимит: безлимит (Premium)")

        print(f"{'='*60}\n")


def main():
    if len(sys.argv) != 2:
        print("Использование: python check_user.py <telegram_id>")
        print("\nПример:")
        print("  python check_user.py 12345")
        sys.exit(1)

    try:
        telegram_id = int(sys.argv[1])
    except ValueError:
        print("❌ Ошибка: telegram_id должен быть числом")
        sys.exit(1)

    check_user(telegram_id)


if __name__ == "__main__":
    main()
