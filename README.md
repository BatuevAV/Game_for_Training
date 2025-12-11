# Комарики - Telegram Мини-Приложение для Тренировки Мозга

Проект для тренировки памяти и реакции через Telegram бот с системой прогрессии, коллекцией комариков и монетизацией.

## Возможности

### Игры
- **Пары комариков** (Memory Pairs) - классическая игра на память с парными карточками
- **Маршрут комарика** (Memory Sequence) - запоминание последовательностей
- **Охота за сигналом** (Reaction Hunt) - тренировка скорости реакции

### Система прогрессии
- Два навыка: Память и Реакция
- Уровни и опыт (XP) с прогрессивной формулой роста
- Система стриков: до 1.5x бонуса за ежедневные тренировки
- Производительность влияет на получаемый XP

### Коллекция комариков
- 4 редкости: Common, Rare, Epic, Legendary
- Каждый комарик фокусируется на определённом навыке
- Прокачка комариков с уровнями и опытом

### Монетизация
- **Бесплатные пользователи**: лимит 8 игр в день
- **Premium подписка**: 
  - Безлимитные игры
  - XP множитель 1.5x
  - Эксклюзивные комарики

## Технологический стек

- **Python 3.9+**
- **aiogram 3.x** - Telegram Bot API
- **FastAPI** - REST API backend
- **SQLAlchemy 2.0** - ORM для базы данных
- **PostgreSQL** - основная база данных
- **Alembic** - миграции базы данных
- **pytest** - тестирование

## Установка и настройка

### 1. Клонирование репозитория

```bash
git clone <repository-url>
cd Testik
```

### 2. Создание виртуального окружения

```bash
python3 -m venv venv
source venv/bin/activate  # На Windows: venv\Scripts\activate
```

### 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 4. Настройка окружения

Создайте файл `.env` на основе `.env.example`:

```bash
cp .env.example .env
```

Отредактируйте `.env` и заполните необходимые параметры:

```env
# База данных PostgreSQL
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/komariki

# Telegram Bot Token (получите у @BotFather)
BOT_TOKEN=your_bot_token_here

# URL backend API (для подключения бота)
BACKEND_URL=http://127.0.0.1:8000

# URL WebApp (для Telegram mini app, должен быть HTTPS)
WEBAPP_URL=https://your-domain.com/webapp
```

### 5. Настройка базы данных

#### Создание базы данных PostgreSQL

```bash
# Войдите в PostgreSQL
psql -U postgres

# Создайте базу данных
CREATE DATABASE komariki;

# Создайте пользователя (опционально)
CREATE USER komariki_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE komariki TO komariki_user;
```

#### Применение миграций

```bash
# Применить все миграции
alembic upgrade head

# Проверить текущую версию
alembic current

# Создать новую миграцию (после изменения моделей)
alembic revision --autogenerate -m "Description of changes"
```

## Запуск проекта

### Запуск FastAPI backend

```bash
uvicorn testik.api:app --reload --host 0.0.0.0 --port 8000
```

API будет доступен по адресу: http://127.0.0.1:8000
Документация Swagger: http://127.0.0.1:8000/docs

### Запуск Telegram бота

```bash
python -m testik.bot
```

### Запуск тестов

```bash
# Все тесты
pytest

# С подробным выводом
pytest -v

# Конкретный тест
pytest tests/test_xp.py -v

# С покрытием кода
pytest --cov=testik --cov-report=html
```

## Структура проекта

```
Testik/
├── testik/                     # Основной пакет
│   ├── __init__.py
│   ├── api.py                  # FastAPI backend
│   ├── bot.py                  # Telegram bot
│   ├── db.py                   # SQLAlchemy модели и настройки БД
│   └── domain/                 # Бизнес-логика
│       ├── __init__.py
│       ├── models.py           # Domain модели (User, Skill, Game и т.д.)
│       └── xp.py               # Расчёт опыта и производительности
├── tests/                      # Тесты
│   ├── __init__.py
│   ├── test_api.py             # Тесты API
│   └── test_xp.py              # Тесты XP системы
├── alembic/                    # Миграции БД
│   ├── versions/               # Файлы миграций
│   └── env.py                  # Настройки Alembic
├── alembic.ini                 # Конфигурация Alembic
├── requirements.txt            # Python зависимости
├── .env.example                # Пример файла окружения
├── .gitignore
└── README.md
```

## API Endpoints

### Аутентификация
- `POST /auth/telegram` - Регистрация/вход через Telegram

### Пользователь
- `GET /me` - Получить информацию о пользователе и навыках
- `GET /users/{user_id}` - Получить пользователя по ID

### Комарики
- `GET /mosquito/types` - Список всех типов комариков
- `GET /mosquito/my` - Коллекция комариков пользователя

### Игровые сессии
- `POST /game/session/start` - Начать игровую сессию
- `POST /game/session/finish` - Завершить игру и получить награды

### Монетизация
- `POST /monetization/check-limit` - Проверить лимит игр
- `POST /monetization/premium/subscribe` - Оформить Premium подписку

## Расчёт XP

### Базовая формула
```
raw_xp = base_xp + bonus_xp * performance_score
total_xp = raw_xp * streak_multiplier * premium_multiplier
```

- `base_xp` = 15
- `bonus_xp` = 25
- `performance_score` - от 0.0 до 1.0, зависит от результата игры
- `streak_multiplier` - от 1.0 до 1.5 (за стрики)
- `premium_multiplier` - 1.5 для Premium пользователей

### Распределение XP по навыкам
- **Memory Pairs / Memory Sequence**: 90% память, 10% реакция
- **Reaction Hunt**: 10% память, 90% реакция

### Требования XP для левелапа
- Уровни 1-10: `40 + 15 * (level - 1)`
- Уровни 11+: `175 + 20 * (level - 11)`

## Разработка

### Добавление новой игры

1. Добавьте тип игры в `domain/models.py`:
```python
class GameType(str, Enum):
    NEW_GAME = "new_game"
```

2. Добавьте функцию расчёта производительности в `domain/xp.py`
3. Обновите `compute_xp_for_game()` в `domain/xp.py`
4. Добавьте обработчики в `bot.py` и эндпоинты в `api.py`

### Создание миграции

```bash
# Автоматическая генерация после изменения моделей
alembic revision --autogenerate -m "Description"

# Ручное создание миграции
alembic revision -m "Description"
```

## Deployment

### Docker (TODO)
```bash
docker-compose up -d
```

### Production checklist
- [ ] Настроить HTTPS для WebApp
- [ ] Настроить production БД (PostgreSQL)
- [ ] Настроить секреты через переменные окружения
- [ ] Настроить логирование
- [ ] Настроить мониторинг (Sentry, Prometheus)
- [ ] Настроить резервное копирование БД
- [ ] Настроить rate limiting на API

## Лицензия

MIT

## Контакты

Вопросы и предложения: [ваш email или telegram]
