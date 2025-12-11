#!/usr/bin/env python3
"""Список всех пользователей в базе данных."""

from dotenv import load_dotenv
load_dotenv()

from testik.db import SessionLocal, UserDB

if SessionLocal:
    with SessionLocal() as session:
        users = session.query(UserDB).all()
        if users:
            print('\nПользователи в базе данных:')
            print('='*80)
            for user in users:
                premium_icon = "⭐" if user.is_premium else "🆓"
                print(f'{premium_icon} ID: {user.id:3d} | Telegram ID: {user.telegram_id:12d} | Username: {user.username or "N/A":20s} | Premium: {user.is_premium}')
            print('='*80)
            print(f'Всего пользователей: {len(users)}\n')
        else:
            print('\n❌ В базе данных нет пользователей\n')
else:
    print('\n❌ База данных не настроена. Проверьте DATABASE_URL в .env\n')
