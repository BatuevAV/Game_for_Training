from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Dict, List, Optional, TypedDict


class Skill(str, Enum):
    MEMORY = "memory"
    REACTION = "reaction"
    MIXED = "mixed"


class Rarity(str, Enum):
    COMMON = "common"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"


@dataclass
class User:
    id: int
    telegram_id: int
    username: Optional[str]
    created_at: datetime
    last_active_at: datetime
    is_premium: bool = False


@dataclass
class SkillStats:
    user_id: int
    memory_level: int = 1
    memory_xp: int = 0
    reaction_level: int = 1
    reaction_xp: int = 0
    daily_streak: int = 0
    last_training_date: Optional[date] = None


@dataclass
class MosquitoType:
    id: int
    name: str
    rarity: Rarity
    focus_skill: Skill
    icon_url: str
    description: str = ""


@dataclass
class UserMosquito:
    id: int
    user_id: int
    mosquito_type_id: int
    level: int = 1
    xp: int = 0
    obtained_at: datetime = field(default_factory=datetime.utcnow)
    source: str = ""


class MemoryPairsResult(TypedDict):
    moves_count: int
    mistakes: int
    time_ms: int


class MemorySequenceResult(TypedDict):
    max_sequence_length: int
    total_correct: int
    total_mistakes: int


class ReactionHuntResult(TypedDict):
    avg_reaction_ms: int
    correct_hits: int
    misses: int


class GameType(str, Enum):
    MEMORY_PAIRS = "memory_pairs"
    MEMORY_SEQUENCE = "memory_sequence"
    REACTION_HUNT = "reaction_hunt"


@dataclass
class GameSession:
    id: int
    user_id: int
    game_type: GameType
    started_at: datetime
    finished_at: datetime
    result: Dict
    gained_memory_xp: int
    gained_reaction_xp: int
    performance_score: float


class AchievementCategory(str, Enum):
    STREAK = "streak"          # Серии дней
    LEVEL = "level"            # Достижение уровней
    GAMES = "games"            # Количество игр
    PERFORMANCE = "performance"  # Производительность
    COLLECTION = "collection"    # Коллекция комариков
    SPECIAL = "special"        # Особые достижения


@dataclass
class Achievement:
    """Шаблон достижения"""
    id: int
    name: str
    description: str
    category: AchievementCategory
    icon: str
    rarity: Rarity
    requirement: Dict  # Условие для получения (например: {"streak": 7})
    reward_xp: int = 0
    reward_coins: int = 0  # Для будущей валюты


@dataclass
class UserAchievement:
    """Полученное достижение пользователя"""
    id: int
    user_id: int
    achievement_id: int
    unlocked_at: datetime
    progress: float = 1.0  # От 0.0 до 1.0

