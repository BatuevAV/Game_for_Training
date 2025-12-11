"""
Система достижений для игры Комарики.

Проверяет условия и разблокирует достижения для пользователей.
"""

from __future__ import annotations

from typing import List, Optional, Dict
from datetime import datetime

from .models import (
    Achievement,
    AchievementCategory,
    Rarity,
    SkillStats,
    User,
)


# Предустановленные достижения
PREDEFINED_ACHIEVEMENTS = [
    # Серии дней
    Achievement(
        id=1,
        name="Первые шаги",
        description="Сыграть первую игру",
        category=AchievementCategory.STREAK,
        icon="🎯",
        rarity=Rarity.COMMON,
        requirement={"games_played": 1},
        reward_xp=10,
    ),
    Achievement(
        id=2,
        name="Неделя тренировок",
        description="7 дней подряд тренировок",
        category=AchievementCategory.STREAK,
        icon="🔥",
        rarity=Rarity.RARE,
        requirement={"streak": 7},
        reward_xp=100,
    ),
    Achievement(
        id=3,
        name="Месяц упорства",
        description="30 дней подряд тренировок",
        category=AchievementCategory.STREAK,
        icon="💪",
        rarity=Rarity.EPIC,
        requirement={"streak": 30},
        reward_xp=500,
    ),
    Achievement(
        id=4,
        name="Железная воля",
        description="100 дней подряд тренировок",
        category=AchievementCategory.STREAK,
        icon="🏆",
        rarity=Rarity.LEGENDARY,
        requirement={"streak": 100},
        reward_xp=2000,
    ),
    
    # Уровни
    Achievement(
        id=5,
        name="Ученик",
        description="Достичь 5 уровня памяти",
        category=AchievementCategory.LEVEL,
        icon="📚",
        rarity=Rarity.COMMON,
        requirement={"memory_level": 5},
        reward_xp=50,
    ),
    Achievement(
        id=6,
        name="Адепт",
        description="Достичь 10 уровня памяти",
        category=AchievementCategory.LEVEL,
        icon="🧠",
        rarity=Rarity.RARE,
        requirement={"memory_level": 10},
        reward_xp=150,
    ),
    Achievement(
        id=7,
        name="Мастер памяти",
        description="Достичь 20 уровня памяти",
        category=AchievementCategory.LEVEL,
        icon="🎓",
        rarity=Rarity.EPIC,
        requirement={"memory_level": 20},
        reward_xp=500,
    ),
    Achievement(
        id=8,
        name="Молния",
        description="Достичь 10 уровня реакции",
        category=AchievementCategory.LEVEL,
        icon="⚡",
        rarity=Rarity.RARE,
        requirement={"reaction_level": 10},
        reward_xp=150,
    ),
    
    # Количество игр
    Achievement(
        id=9,
        name="Новичок",
        description="Сыграть 10 игр",
        category=AchievementCategory.GAMES,
        icon="🎮",
        rarity=Rarity.COMMON,
        requirement={"games_played": 10},
        reward_xp=50,
    ),
    Achievement(
        id=10,
        name="Энтузиаст",
        description="Сыграть 50 игр",
        category=AchievementCategory.GAMES,
        icon="🎯",
        rarity=Rarity.RARE,
        requirement={"games_played": 50},
        reward_xp=200,
    ),
    Achievement(
        id=11,
        name="Ветеран",
        description="Сыграть 100 игр",
        category=AchievementCategory.GAMES,
        icon="🏅",
        rarity=Rarity.EPIC,
        requirement={"games_played": 100},
        reward_xp=500,
    ),
    Achievement(
        id=12,
        name="Легенда",
        description="Сыграть 500 игр",
        category=AchievementCategory.GAMES,
        icon="👑",
        rarity=Rarity.LEGENDARY,
        requirement={"games_played": 500},
        reward_xp=2000,
    ),
    
    # Производительность
    Achievement(
        id=13,
        name="Идеальная игра",
        description="Завершить игру с результатом 100%",
        category=AchievementCategory.PERFORMANCE,
        icon="💯",
        rarity=Rarity.EPIC,
        requirement={"perfect_game": 1},
        reward_xp=300,
    ),
    Achievement(
        id=14,
        name="Скоростной демон",
        description="Завершить игру Memory Pairs менее чем за 30 секунд",
        category=AchievementCategory.PERFORMANCE,
        icon="🚀",
        rarity=Rarity.EPIC,
        requirement={"fast_pairs": 30000},  # миллисекунды
        reward_xp=250,
    ),
    
    # Особые
    Achievement(
        id=15,
        name="Комарик Premium",
        description="Оформить Premium подписку",
        category=AchievementCategory.SPECIAL,
        icon="⭐",
        rarity=Rarity.LEGENDARY,
        requirement={"is_premium": True},
        reward_xp=0,
    ),
]


def check_achievement_unlocked(
    achievement: Achievement,
    user: User,
    skills: SkillStats,
    total_games: int = 0,
    last_game_result: Optional[Dict] = None,
) -> bool:
    """
    Проверить, выполнены ли условия для разблокировки достижения.
    """
    req = achievement.requirement
    
    # Проверка серий
    if "streak" in req:
        if skills.daily_streak >= req["streak"]:
            return True
    
    # Проверка уровней
    if "memory_level" in req:
        if skills.memory_level >= req["memory_level"]:
            return True
    
    if "reaction_level" in req:
        if skills.reaction_level >= req["reaction_level"]:
            return True
    
    # Проверка количества игр
    if "games_played" in req:
        if total_games >= req["games_played"]:
            return True
    
    # Проверка производительности
    if "perfect_game" in req and last_game_result:
        performance_score = last_game_result.get("performance_score", 0)
        if performance_score >= 1.0:
            return True
    
    if "fast_pairs" in req and last_game_result:
        game_type = last_game_result.get("game_type")
        time_ms = last_game_result.get("time_ms", 999999)
        if game_type == "memory_pairs" and time_ms <= req["fast_pairs"]:
            return True
    
    # Проверка Premium
    if "is_premium" in req:
        if user.is_premium == req["is_premium"]:
            return True
    
    return False


def calculate_achievement_progress(
    achievement: Achievement,
    user: User,
    skills: SkillStats,
    total_games: int = 0,
) -> float:
    """
    Рассчитать прогресс достижения (от 0.0 до 1.0).
    """
    req = achievement.requirement
    
    if "streak" in req:
        return min(1.0, skills.daily_streak / req["streak"])
    
    if "memory_level" in req:
        return min(1.0, skills.memory_level / req["memory_level"])
    
    if "reaction_level" in req:
        return min(1.0, skills.reaction_level / req["reaction_level"])
    
    if "games_played" in req:
        return min(1.0, total_games / req["games_played"])
    
    # Для производительных и особых достижений прогресс либо 0, либо 1
    return 0.0


def get_newly_unlocked_achievements(
    user: User,
    skills: SkillStats,
    total_games: int,
    unlocked_achievement_ids: List[int],
    last_game_result: Optional[Dict] = None,
) -> List[Achievement]:
    """
    Получить список новых разблокированных достижений.
    """
    newly_unlocked = []
    
    for achievement in PREDEFINED_ACHIEVEMENTS:
        # Пропускаем уже разблокированные
        if achievement.id in unlocked_achievement_ids:
            continue
        
        # Проверяем условия
        if check_achievement_unlocked(
            achievement, user, skills, total_games, last_game_result
        ):
            newly_unlocked.append(achievement)
    
    return newly_unlocked
