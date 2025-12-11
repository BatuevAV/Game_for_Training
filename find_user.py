#!/usr/bin/env python3
"""
Поиск пользователя по разным параметрам.

Использование:
    python find_user.py --user-id <id>
    python find_user.py --telegram-id <id>
    python find_user.py --username <username>
"""

import argparse
from dotenv import load_dotenv
load_dotenv()

from testik.db import SessionLocal, UserDB, SkillStatsDB


def find_user(user_id=None, telegram_id=None, username=None):
    """Найти пользователя по разным критериям."""
    if not SessionLocal:
        print("❌ База данных не настроена. Проверьте DATABASE_URL в .env")
        return

    with SessionLocal() as session:
        query = session.query(UserDB)
        
        if user_id is not None:
            user = session.get(UserDB, user_id)
            users = [user] if user else []
        elif telegram_id is not None:
            users = query.filter(UserDB.telegram_id == telegram_id).all()
        elif username is not None:
            users = query.filter(UserDB.username.ilike(f"%{username}%")).all()
        else:
            print("❌ Укажите хотя бы один параметр поиска")
            return

        if not users:
            print("\n❌ Пользователь не найден\n")
            if user_id:
                print(f"Попробуйте: python list_users.py  # чтобы увидеть всех пользователей")
            return

        for user in users:
            if not user:
                continue
                
            stats = session.get(SkillStatsDB, user.id)
            
            premium_icon = "⭐" if user.is_premium else "🆓"
            print(f"\n{premium_icon} Найден пользователь:")
            print("="*70)
            print(f"  ID в базе:       {user.id}")
            print(f"  Telegram ID:     {user.telegram_id}")
            print(f"  Username:        {user.username or 'N/A'}")
            print(f"  Статус:          {'Premium ⭐' if user.is_premium else 'Free 🆓'}")
            print(f"  Зарегистрирован: {user.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  Последняя актив: {user.last_active_at.strftime('%Y-%m-%d %H:%M:%S')}")
            
            if stats:
                print(f"\n  📊 Навыки:")
                print(f"     Память:   Уровень {stats.memory_level} (XP: {stats.memory_xp})")
                print(f"     Реакция:  Уровень {stats.reaction_level} (XP: {stats.reaction_xp})")
                print(f"     Серия:    {stats.daily_streak} дней")
            
            print("="*70)
            print(f"\n💡 Для проверки через API используйте:")
            print(f"   curl http://127.0.0.1:8000/me?user_id={user.id}\n")


def main():
    parser = argparse.ArgumentParser(description="Поиск пользователя в базе данных")
    parser.add_argument("--user-id", type=int, help="ID пользователя в базе")
    parser.add_argument("--telegram-id", type=int, help="Telegram ID пользователя")
    parser.add_argument("--username", type=str, help="Username пользователя")
    
    args = parser.parse_args()
    
    if not any([args.user_id, args.telegram_id, args.username]):
        parser.print_help()
        print("\nПример:")
        print("  python find_user.py --user-id 1")
        print("  python find_user.py --telegram-id 997743143")
        print("  python find_user.py --username sankaapelsin")
        return
    
    find_user(
        user_id=args.user_id,
        telegram_id=args.telegram_id,
        username=args.username
    )


if __name__ == "__main__":
    main()
