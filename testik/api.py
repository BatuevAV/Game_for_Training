"""
FastAPI backend skeleton for the 'Комарики' brain-training app.

This is a simplified, in-memory implementation of the API we described:
- /auth/telegram – register/auth user
- /me – get current user + skills
- /mosquito/types – list of mosquito types
- /mosquito/my – user's collection
- /game/session/start – start a game session
- /game/session/finish – finish a game session, compute XP and rewards

Persistence is deliberately in-memory to keep the example compact and easy
to extend later with a real database.
"""

from __future__ import annotations

import random
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .domain.models import (
    GameType,
    MosquitoType,
    Rarity,
    Skill,
    SkillStats,
    User,
    UserMosquito,
)
from .domain.xp import XpGain, compute_xp_for_game, skill_xp_to_next
from .domain.leaderboard import (
    LeaderboardType,
    TimePeriod,
    LeaderboardEntry,
    get_leaderboard,
)
from . import db as db_mod


app = FastAPI(title="Комарики API", version="0.1.0")


# --- Storage: DB (if configured) or in-memory fallback ---

USE_DB = db_mod.engine is not None

# Monetization / limits (for free users)
FREE_DAILY_GAMES_LIMIT = 8
PREMIUM_XP_MULTIPLIER = 1.5

_users: Dict[int, User] = {}
_skill_stats: Dict[int, SkillStats] = {}
_mosquito_types: Dict[int, MosquitoType] = {}
_user_mosquitoes: Dict[int, List[UserMosquito]] = {}
_sessions: Dict[int, Dict] = {}

_user_id_seq = 1
_mosquito_type_id_seq = 1
_user_mosquito_id_seq = 1
_session_id_seq = 1


def reset_state() -> None:
    """
    Reset state.
    - If DB is configured, (re)create tables.
    - Otherwise reset in-memory storage (used in unit tests).
    """
    global _users, _skill_stats, _mosquito_types, _user_mosquitoes, _sessions
    global _user_id_seq, _mosquito_type_id_seq, _user_mosquito_id_seq, _session_id_seq

    if USE_DB and db_mod.engine is not None:
        db_mod.Base.metadata.create_all(db_mod.engine)
    else:
        _users = {}
        _skill_stats = {}
        _mosquito_types = {}
        _user_mosquitoes = {}
        _sessions = {}

        _user_id_seq = 1
        _mosquito_type_id_seq = 1
        _user_mosquito_id_seq = 1
        _session_id_seq = 1

    _init_default_mosquito_types()


def _init_default_mosquito_types() -> None:
    """
    Populate a small set of mosquito types, either in DB or in-memory.
    """
    global _mosquito_type_id_seq

    base_types = [
        ("Комар-память", Rarity.COMMON, Skill.MEMORY, "🧠"),
        ("Комар-реакция", Rarity.COMMON, Skill.REACTION, "⚡"),
        ("Комар-концентрация", Rarity.RARE, Skill.MEMORY, "🎯"),
        ("Комар-молния", Rarity.RARE, Skill.REACTION, "🌩"),
        ("Комар-легенда", Rarity.LEGENDARY, Skill.MIXED, "👑"),
    ]

    if USE_DB and db_mod.SessionLocal is not None:
        with db_mod.SessionLocal() as session:
            existing = session.query(db_mod.MosquitoTypeDB).count()
            if existing:
                return
            for name, rarity, focus, icon in base_types:
                mt = db_mod.MosquitoTypeDB(
                    name=name,
                    rarity=rarity,
                    focus_skill=focus,
                    icon_url=icon,
                    description="",
                )
                session.add(mt)
            session.commit()
    else:
        if _mosquito_types:
            return
        for name, rarity, focus, icon in base_types:
            mt_id = _mosquito_type_id_seq
            _mosquito_type_id_seq += 1
            _mosquito_types[mt_id] = MosquitoType(
                id=mt_id,
                name=name,
                rarity=rarity,
                focus_skill=focus,
                icon_url=icon,
                description="",
            )


# Initialize mosquitoes on import
reset_state()


# --- Helpers ---


def _get_or_create_user(telegram_id: int, username: Optional[str]) -> User:
    global _user_id_seq

    if USE_DB and db_mod.SessionLocal is not None:
        with db_mod.SessionLocal() as session:
            existing = (
                session.query(db_mod.UserDB)
                .filter(db_mod.UserDB.telegram_id == telegram_id)
                .one_or_none()
            )
            now = datetime.utcnow()
            if existing:
                if username and existing.username != username:
                    existing.username = username
                existing.last_active_at = now
                session.commit()
                return User(
                    id=existing.id,
                    telegram_id=existing.telegram_id,
                    username=existing.username,
                    created_at=existing.created_at,
                    last_active_at=existing.last_active_at,
                    is_premium=existing.is_premium,
                )

            user_db = db_mod.UserDB(
                telegram_id=telegram_id,
                username=username,
                created_at=now,
                last_active_at=now,
            )
            session.add(user_db)
            session.flush()

            stats_db = db_mod.SkillStatsDB(user_id=user_db.id)
            session.add(stats_db)
            session.commit()

            return User(
                id=user_db.id,
                telegram_id=user_db.telegram_id,
                username=user_db.username,
                created_at=user_db.created_at,
                last_active_at=user_db.last_active_at,
                is_premium=user_db.is_premium,
            )

    for user in _users.values():
        if user.telegram_id == telegram_id:
            # Update username if changed
            if username and user.username != username:
                user.username = username
            user.last_active_at = datetime.utcnow()
            return user

    user_id = _user_id_seq
    _user_id_seq += 1
    now = datetime.utcnow()
    user = User(
        id=user_id,
        telegram_id=telegram_id,
        username=username,
        created_at=now,
        last_active_at=now,
    )
    _users[user_id] = user
    _skill_stats[user_id] = SkillStats(user_id=user_id)
    _user_mosquitoes[user_id] = []
    return user


def _get_skill_stats(user_id: int) -> SkillStats:
    if USE_DB and db_mod.SessionLocal is not None:
        with db_mod.SessionLocal() as session:
            stats_db = session.get(db_mod.SkillStatsDB, user_id)
            if not stats_db:
                raise HTTPException(
                    status_code=404, detail="Skill stats not found for user"
                )
            return SkillStats(
                user_id=stats_db.user_id,
                memory_level=stats_db.memory_level,
                memory_xp=stats_db.memory_xp,
                reaction_level=stats_db.reaction_level,
                reaction_xp=stats_db.reaction_xp,
                daily_streak=stats_db.daily_streak,
                last_training_date=stats_db.last_training_date,
            )

    try:
        return _skill_stats[user_id]
    except KeyError:
        raise HTTPException(status_code=404, detail="Skill stats not found for user")


def _update_daily_streak(stats: SkillStats, today: date) -> None:
    if stats.last_training_date is None:
        stats.daily_streak = 1
    else:
        delta = today - stats.last_training_date
        if delta == timedelta(days=0):
            # same day: keep streak
            return
        if delta == timedelta(days=1):
            stats.daily_streak += 1
        else:
            stats.daily_streak = 1
    stats.last_training_date = today


def _apply_xp(stats: SkillStats, gain: XpGain) -> None:
    from .domain.xp import skill_xp_to_next

    stats.memory_xp += gain.memory_xp
    while stats.memory_xp >= skill_xp_to_next(stats.memory_level):
        stats.memory_xp -= skill_xp_to_next(stats.memory_level)
        stats.memory_level += 1

    stats.reaction_xp += gain.reaction_xp
    while stats.reaction_xp >= skill_xp_to_next(stats.reaction_level):
        stats.reaction_xp -= skill_xp_to_next(stats.reaction_level)
        stats.reaction_level += 1

    if USE_DB and db_mod.SessionLocal is not None:
        with db_mod.SessionLocal() as session:
            stats_db = session.get(db_mod.SkillStatsDB, stats.user_id)
            if stats_db:
                stats_db.memory_level = stats.memory_level
                stats_db.memory_xp = stats.memory_xp
                stats_db.reaction_level = stats.reaction_level
                stats_db.reaction_xp = stats.reaction_xp
                stats_db.daily_streak = stats.daily_streak
                stats_db.last_training_date = stats.last_training_date
                session.commit()


def _roll_reward(user_id: int, perf: float) -> Optional[UserMosquito]:
    """
    Very simplified reward logic based on performance.
    """
    global _user_mosquito_id_seq

    if perf >= 0.8:
        chance = 0.4
    elif perf >= 0.6:
        chance = 0.25
    elif perf >= 0.4:
        chance = 0.15
    else:
        chance = 0.05

    if random.random() > chance:
        return None

    if USE_DB and db_mod.SessionLocal is not None:
        with db_mod.SessionLocal() as session:
            items = session.query(db_mod.MosquitoTypeDB).all()
            if not items:
                return None
            mt = random.choice(items)
            user_mosquito_db = db_mod.UserMosquitoDB(
                user_id=user_id,
                mosquito_type_id=mt.id,
                source="drop",
            )
            session.add(user_mosquito_db)
            session.commit()
            return UserMosquito(
                id=user_mosquito_db.id,
                user_id=user_mosquito_db.user_id,
                mosquito_type_id=user_mosquito_db.mosquito_type_id,
                level=user_mosquito_db.level,
                xp=user_mosquito_db.xp,
                obtained_at=user_mosquito_db.obtained_at,
                source=user_mosquito_db.source,
            )

    # Choose a random mosquito type (in-memory)
    mosquito_type = random.choice(list(_mosquito_types.values()))
    um_id = _user_mosquito_id_seq
    _user_mosquito_id_seq += 1
    user_mosquito = UserMosquito(
        id=um_id,
        user_id=user_id,
        mosquito_type_id=mosquito_type.id,
        source="drop",
    )
    _user_mosquitoes[user_id].append(user_mosquito)
    return user_mosquito


def _check_and_unlock_achievements(
    user_id: int, 
    performance_score: float,
    game_result: dict,
) -> List[int]:
    """
    Проверить и разблокировать новые достижения после завершения игры.
    Возвращает список ID разблокированных достижений.
    """
    from .domain.achievements import get_newly_unlocked_achievements
    
    if not USE_DB or not db_mod.SessionLocal:
        return []
    
    with db_mod.SessionLocal() as session:
        # Получаем данные пользователя
        user_db = session.get(db_mod.UserDB, user_id)
        if not user_db:
            return []
        
        skills_db = session.get(db_mod.SkillStatsDB, user_id)
        if not skills_db:
            return []
        
        user = User(
            id=user_db.id,
            telegram_id=user_db.telegram_id,
            username=user_db.username,
            created_at=user_db.created_at,
            last_active_at=user_db.last_active_at,
            is_premium=user_db.is_premium,
        )
        
        skills = SkillStats(
            user_id=skills_db.user_id,
            memory_level=skills_db.memory_level,
            memory_xp=skills_db.memory_xp,
            reaction_level=skills_db.reaction_level,
            reaction_xp=skills_db.reaction_xp,
            daily_streak=skills_db.daily_streak,
            last_training_date=skills_db.last_training_date,
        )
        
        # Получаем уже разблокированные достижения
        unlocked = session.query(db_mod.UserAchievementDB).filter(
            db_mod.UserAchievementDB.user_id == user_id
        ).all()
        unlocked_ids = [ua.achievement_id for ua in unlocked]
        
        # Считаем общее количество игр
        total_games = session.query(db_mod.GameSessionDB).filter(
            db_mod.GameSessionDB.user_id == user_id
        ).count()
        
        # Формируем данные последней игры для проверки достижений
        last_game_result = {
            "performance_score": performance_score,
            **game_result
        }
        
        # Проверяем новые достижения
        newly_unlocked = get_newly_unlocked_achievements(
            user=user,
            skills=skills,
            total_games=total_games,
            unlocked_achievement_ids=unlocked_ids,
            last_game_result=last_game_result,
        )
        
        # Сохраняем новые достижения
        new_achievement_ids = []
        for achievement in newly_unlocked:
            user_ach = db_mod.UserAchievementDB(
                user_id=user_id,
                achievement_id=achievement.id,
                unlocked_at=datetime.utcnow(),
                progress=1.0,
            )
            session.add(user_ach)
            new_achievement_ids.append(achievement.id)
            
            # Начисляем награду за достижение
            if achievement.reward_xp > 0:
                skills_db.memory_xp += achievement.reward_xp // 2
                skills_db.reaction_xp += achievement.reward_xp // 2
        
        if new_achievement_ids:
            session.commit()
        
        return new_achievement_ids


# --- Pydantic schemas ---


class UserOut(BaseModel):
    id: int
    telegram_id: int
    username: Optional[str]
    is_premium: bool = False


class SkillStatsOut(BaseModel):
    memory_level: int
    memory_xp: int
    memory_xp_to_next: int
    reaction_level: int
    reaction_xp: int
    reaction_xp_to_next: int
    daily_streak: int


class AuthTelegramRequest(BaseModel):
    telegram_id: int
    username: Optional[str] = None


class AuthTelegramResponse(BaseModel):
    token: str
    user: UserOut
    skills: SkillStatsOut


class MeResponse(BaseModel):
    user: UserOut
    skills: SkillStatsOut


class MosquitoTypeOut(BaseModel):
    id: int
    name: str
    rarity: Rarity
    focus_skill: Skill
    icon_url: str
    description: str


class UserMosquitoOut(BaseModel):
    id: int
    mosquito_type_id: int
    level: int
    xp: int
    obtained_at: datetime
    source: str


class GameSessionStartRequest(BaseModel):
    user_id: int
    game_type: GameType
    difficulty: Optional[str] = "easy"


class GameSessionStartResponse(BaseModel):
    session_id: int
    game_type: GameType
    config: dict


class GameSessionFinishRequest(BaseModel):
    session_id: int
    result: dict


class GameSessionFinishResponse(BaseModel):
    updated_skills: SkillStatsOut
    gained_xp: XpGain
    reward: Optional[UserMosquitoOut]


class ProgressDayOut(BaseModel):
    date: date
    games_count: int
    memory_xp: int
    reaction_xp: int
    avg_reaction_ms: Optional[float] = None
    best_sequence_length: Optional[int] = None


class ProgressHistoryOut(BaseModel):
    user: UserOut
    skills: SkillStatsOut
    days: List[ProgressDayOut]


def _build_skill_out(stats: SkillStats) -> SkillStatsOut:
    return SkillStatsOut(
        memory_level=stats.memory_level,
        memory_xp=stats.memory_xp,
        memory_xp_to_next=skill_xp_to_next(stats.memory_level),
        reaction_level=stats.reaction_level,
        reaction_xp=stats.reaction_xp,
        reaction_xp_to_next=skill_xp_to_next(stats.reaction_level),
        daily_streak=stats.daily_streak,
    )


def _build_user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        telegram_id=user.telegram_id,
        username=user.username,
        is_premium=getattr(user, "is_premium", False),
    )


# --- Endpoints ---


@app.post("/auth/telegram", response_model=AuthTelegramResponse)
def auth_telegram(payload: AuthTelegramRequest) -> AuthTelegramResponse:
    """
    Simplified Telegram auth: in real life you must validate initData signature.
    Here we accept telegram_id and optional username and create a user.
    """
    user = _get_or_create_user(payload.telegram_id, payload.username)
    skills = _get_skill_stats(user.id)
    token = str(user.id)
    return AuthTelegramResponse(
        token=token,
        user=_build_user_out(user),
        skills=_build_skill_out(skills),
    )


@app.get("/me", response_model=MeResponse)
def get_me(user_id: int) -> MeResponse:
    if USE_DB and db_mod.SessionLocal is not None:
        with db_mod.SessionLocal() as session:
            user_db = session.get(db_mod.UserDB, user_id)
            if not user_db:
                raise HTTPException(status_code=404, detail="User not found")
            skills = _get_skill_stats(user_db.id)
            user = User(
                id=user_db.id,
                telegram_id=user_db.telegram_id,
                username=user_db.username,
                created_at=user_db.created_at,
                last_active_at=user_db.last_active_at,
                is_premium=user_db.is_premium,
            )
            return MeResponse(
                user=_build_user_out(user),
                skills=_build_skill_out(skills),
            )

    user = _users.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    skills = _get_skill_stats(user.id)
    return MeResponse(user=_build_user_out(user), skills=_build_skill_out(skills))


@app.get("/mosquito/types", response_model=List[MosquitoTypeOut])
def list_mosquito_types() -> List[MosquitoTypeOut]:
    if USE_DB and db_mod.SessionLocal is not None:
        with db_mod.SessionLocal() as session:
            items = session.query(db_mod.MosquitoTypeDB).all()
            return [
                MosquitoTypeOut(
                    id=m.id,
                    name=m.name,
                    rarity=m.rarity,
                    focus_skill=m.focus_skill,
                    icon_url=m.icon_url,
                    description=m.description,
                )
                for m in items
            ]

    return [
        MosquitoTypeOut(
            id=m.id,
            name=m.name,
            rarity=m.rarity,
            focus_skill=m.focus_skill,
            icon_url=m.icon_url,
            description=m.description,
        )
        for m in _mosquito_types.values()
    ]


@app.get("/mosquito/my", response_model=List[UserMosquitoOut])
def list_my_mosquitoes(user_id: int) -> List[UserMosquitoOut]:
    if USE_DB and db_mod.SessionLocal is not None:
        with db_mod.SessionLocal() as session:
            user = session.get(db_mod.UserDB, user_id)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            items = (
                session.query(db_mod.UserMosquitoDB)
                .filter(db_mod.UserMosquitoDB.user_id == user_id)
                .all()
            )
            return [
                UserMosquitoOut(
                    id=um.id,
                    mosquito_type_id=um.mosquito_type_id,
                    level=um.level,
                    xp=um.xp,
                    obtained_at=um.obtained_at,
                    source=um.source,
                )
                for um in items
            ]

    if user_id not in _users:
        raise HTTPException(status_code=404, detail="User not found")
    return [
        UserMosquitoOut(
            id=um.id,
            mosquito_type_id=um.mosquito_type_id,
            level=um.level,
            xp=um.xp,
            obtained_at=um.obtained_at,
            source=um.source,
        )
        for um in _user_mosquitoes.get(user_id, [])
    ]


@app.post("/game/session/start", response_model=GameSessionStartResponse)
def start_session(payload: GameSessionStartRequest) -> GameSessionStartResponse:
    global _session_id_seq

    if USE_DB and db_mod.SessionLocal is not None:
        with db_mod.SessionLocal() as session:
            user_db = session.get(db_mod.UserDB, payload.user_id)
            if not user_db:
                raise HTTPException(status_code=404, detail="User not found")
            if not user_db.is_premium:
                today = date.today()
                since_dt = datetime.combine(today, datetime.min.time())
                games_today = (
                    session.query(db_mod.GameSessionDB)
                    .filter(
                        db_mod.GameSessionDB.user_id == payload.user_id,
                        db_mod.GameSessionDB.started_at >= since_dt,
                    )
                    .count()
                )
                if games_today >= FREE_DAILY_GAMES_LIMIT:
                    raise HTTPException(
                        status_code=429,
                        detail={
                            "error": "daily_limit_exceeded",
                            "limit": FREE_DAILY_GAMES_LIMIT,
                            "used": games_today,
                        },
                    )
    else:
        if payload.user_id not in _users:
            raise HTTPException(status_code=404, detail="User not found")

    session_id = _session_id_seq
    _session_id_seq += 1

    # Very small config examples
    if payload.game_type == GameType.MEMORY_PAIRS:
        config = {"rows": 3, "columns": 4}
    elif payload.game_type == GameType.MEMORY_SEQUENCE:
        config = {"points": 6, "initial_length": 3}
    elif payload.game_type == GameType.REACTION_HUNT:
        config = {"duration_sec": 30}
    else:
        raise HTTPException(status_code=400, detail="Unsupported game type")

    _sessions[session_id] = {
        "user_id": payload.user_id,
        "game_type": payload.game_type,
        "started_at": datetime.utcnow(),
    }

    return GameSessionStartResponse(
        session_id=session_id, game_type=payload.game_type, config=config
    )


@app.post("/game/session/finish", response_model=GameSessionFinishResponse)
def finish_session(payload: GameSessionFinishRequest) -> GameSessionFinishResponse:
    session_data = _sessions.get(payload.session_id)
    if not session_data:
        raise HTTPException(status_code=404, detail="Session not found")

    user_id = session_data["user_id"]
    game_type: GameType = session_data["game_type"]

    is_premium = False
    if USE_DB and db_mod.SessionLocal is not None:
        with db_mod.SessionLocal() as db_session:
            user_db = db_session.get(db_mod.UserDB, user_id)
            if user_db:
                is_premium = bool(user_db.is_premium)

    stats = _get_skill_stats(user_id)
    _update_daily_streak(stats, today=date.today())

    gain = compute_xp_for_game(
        game_type=game_type,
        result=payload.result,
        daily_streak=stats.daily_streak,
    )

    if is_premium:
        gain.memory_xp = int(round(gain.memory_xp * PREMIUM_XP_MULTIPLIER))
        gain.reaction_xp = int(round(gain.reaction_xp * PREMIUM_XP_MULTIPLIER))

    _apply_xp(stats, gain)

    reward = _roll_reward(user_id, gain.performance_score)

    if USE_DB and db_mod.SessionLocal is not None:
        with db_mod.SessionLocal() as db_session:
            session_db = db_mod.GameSessionDB(
                user_id=user_id,
                game_type=game_type,
                started_at=session_data["started_at"],
                finished_at=datetime.utcnow(),
                result=payload.result,
                gained_memory_xp=gain.memory_xp,
                gained_reaction_xp=gain.reaction_xp,
                performance_score=gain.performance_score,
            )
            db_session.add(session_db)
            db_session.commit()

    reward_out: Optional[UserMosquitoOut]
    if reward is None:
        reward_out = None
    else:
        reward_out = UserMosquitoOut(
            id=reward.id,
            mosquito_type_id=reward.mosquito_type_id,
            level=reward.level,
            xp=reward.xp,
            obtained_at=reward.obtained_at,
            source=reward.source,
        )

    # Проверяем новые достижения
    _check_and_unlock_achievements(user_id, gain.performance_score, payload.result)

    return GameSessionFinishResponse(
        updated_skills=_build_skill_out(stats),
        gained_xp=gain,
        reward=reward_out,
    )


@app.get("/progress/history", response_model=ProgressHistoryOut)
def get_progress_history(user_id: int, days: int = 30) -> ProgressHistoryOut:
    """
    Aggregate per-day progress for a user over the last N days.
    Requires a real database; in in-memory mode returns an empty history.
    """
    if days <= 0:
        days = 30

    if USE_DB and db_mod.SessionLocal is not None:
        with db_mod.SessionLocal() as session:
            user_db = session.get(db_mod.UserDB, user_id)
            if not user_db:
                raise HTTPException(status_code=404, detail="User not found")

            skills = _get_skill_stats(user_id)

            since_date = date.today() - timedelta(days=days - 1)
            since_dt = datetime.combine(since_date, datetime.min.time())

            qs = (
                session.query(db_mod.GameSessionDB)
                .filter(
                    db_mod.GameSessionDB.user_id == user_id,
                    db_mod.GameSessionDB.started_at >= since_dt,
                )
                .order_by(db_mod.GameSessionDB.started_at)
            )

            buckets: Dict[date, Dict] = {}
            for s in qs:
                d = s.started_at.date()
                b = buckets.setdefault(
                    d,
                    {
                        "games_count": 0,
                        "memory_xp": 0,
                        "reaction_xp": 0,
                        "reaction_ms_sum": 0.0,
                        "reaction_ms_count": 0,
                        "best_sequence_length": None,
                    },
                )
                b["games_count"] += 1
                b["memory_xp"] += s.gained_memory_xp
                b["reaction_xp"] += s.gained_reaction_xp

                if s.game_type == GameType.REACTION_HUNT and s.result:
                    avg_ms = s.result.get("avg_reaction_ms")
                    if isinstance(avg_ms, (int, float)):
                        b["reaction_ms_sum"] += float(avg_ms)
                        b["reaction_ms_count"] += 1

                if s.game_type == GameType.MEMORY_SEQUENCE and s.result:
                    max_len = s.result.get("max_sequence_length")
                    if isinstance(max_len, int):
                        if (
                            b["best_sequence_length"] is None
                            or max_len > b["best_sequence_length"]
                        ):
                            b["best_sequence_length"] = max_len

            days_out: List[ProgressDayOut] = []
            for d in sorted(buckets.keys()):
                b = buckets[d]
                if b["reaction_ms_count"] > 0:
                    avg_ms = b["reaction_ms_sum"] / b["reaction_ms_count"]
                else:
                    avg_ms = None
                days_out.append(
                    ProgressDayOut(
                        date=d,
                        games_count=b["games_count"],
                        memory_xp=b["memory_xp"],
                        reaction_xp=b["reaction_xp"],
                        avg_reaction_ms=avg_ms,
                        best_sequence_length=b["best_sequence_length"],
                    )
                )

            user = User(
                id=user_db.id,
                telegram_id=user_db.telegram_id,
                username=user_db.username,
                created_at=user_db.created_at,
                last_active_at=user_db.last_active_at,
            )

            return ProgressHistoryOut(
                user=_build_user_out(user),
                skills=_build_skill_out(skills),
                days=days_out,
            )

    # In-memory mode: limited information, return empty history
    user = _users.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    skills = _get_skill_stats(user.id)
    return ProgressHistoryOut(
        user=_build_user_out(user),
        skills=_build_skill_out(skills),
        days=[],
    )


# --- Premium Management Endpoints ---


class SetPremiumRequest(BaseModel):
    user_id: int
    is_premium: bool


class SetPremiumResponse(BaseModel):
    success: bool
    user: UserOut
    message: str


@app.post("/admin/set-premium", response_model=SetPremiumResponse)
def set_premium(payload: SetPremiumRequest) -> SetPremiumResponse:
    """
    Установить или снять Premium статус для пользователя.
    В production это должно быть защищено авторизацией админа.
    """
    if USE_DB and db_mod.SessionLocal is not None:
        with db_mod.SessionLocal() as session:
            user_db = session.get(db_mod.UserDB, payload.user_id)
            if not user_db:
                raise HTTPException(status_code=404, detail="User not found")
            
            old_status = user_db.is_premium
            user_db.is_premium = payload.is_premium
            session.commit()
            
            user = User(
                id=user_db.id,
                telegram_id=user_db.telegram_id,
                username=user_db.username,
                created_at=user_db.created_at,
                last_active_at=user_db.last_active_at,
                is_premium=user_db.is_premium,
            )
            
            status_msg = "Premium активирован" if payload.is_premium else "Premium деактивирован"
            return SetPremiumResponse(
                success=True,
                user=_build_user_out(user),
                message=f"{status_msg} для пользователя {user.username or user.telegram_id}",
            )
    
    # In-memory version
    user = _users.get(payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.is_premium = payload.is_premium
    status_msg = "Premium активирован" if payload.is_premium else "Premium деактивирован"
    
    return SetPremiumResponse(
        success=True,
        user=_build_user_out(user),
        message=f"{status_msg} для пользователя {user.username or user.telegram_id}",
    )


# --- Achievements Endpoints ---


class AchievementOut(BaseModel):
    id: int
    name: str
    description: str
    category: str
    icon: str
    rarity: str
    reward_xp: int
    reward_coins: int
    progress: Optional[float] = None
    unlocked_at: Optional[datetime] = None


class AchievementsResponse(BaseModel):
    achievements: List[AchievementOut]
    total: int
    unlocked_count: int


# ============================================================================
# LEADERBOARD MODELS & ENDPOINTS
# ============================================================================

class LeaderboardEntryOut(BaseModel):
    rank: int
    user_id: int
    telegram_id: int
    username: Optional[str]
    first_name: Optional[str]
    value: int
    is_premium: bool


class LeaderboardResponse(BaseModel):
    entries: List[LeaderboardEntryOut]
    total: int
    leaderboard_type: str
    time_period: str


@app.get("/leaderboard", response_model=LeaderboardResponse)
def get_leaderboard_endpoint(
    type: LeaderboardType = LeaderboardType.TOTAL_XP,
    period: TimePeriod = TimePeriod.ALL_TIME,
    limit: int = 100,
    user_id: Optional[int] = None
) -> LeaderboardResponse:
    """
    Получить таблицу лидеров.
    
    Parameters:
    - type: тип рейтинга (total_xp, memory_level, reaction_level, games_played, current_streak)
    - period: период времени (all_time, weekly, monthly)
    - limit: максимальное количество записей (по умолчанию 100)
    - user_id: ID пользователя для включения в результаты, даже если не в топе
    """
    if not USE_DB:
        raise HTTPException(status_code=501, detail="Database not configured")
    
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 1000")
    
    with db_mod.Session() as session:
        entries = get_leaderboard(
            session=session,
            leaderboard_type=type,
            time_period=period,
            limit=limit,
            user_id=user_id
        )
        
        entries_out = [
            LeaderboardEntryOut(
                rank=entry.rank,
                user_id=entry.user_id,
                telegram_id=entry.telegram_id,
                username=entry.username,
                first_name=entry.first_name,
                value=entry.value,
                is_premium=entry.is_premium
            )
            for entry in entries
        ]
        
        return LeaderboardResponse(
            entries=entries_out,
            total=len(entries_out),
            leaderboard_type=type.value,
            time_period=period.value
        )


# ============================================================================
# ACHIEVEMENTS ENDPOINTS
# ============================================================================

@app.get("/achievements", response_model=List[AchievementOut])
def list_achievements() -> List[AchievementOut]:
    """Получить список всех доступных достижений."""
    from .domain.achievements import PREDEFINED_ACHIEVEMENTS
    
    return [
        AchievementOut(
            id=ach.id,
            name=ach.name,
            description=ach.description,
            category=ach.category.value,
            icon=ach.icon,
            rarity=ach.rarity.value,
            reward_xp=ach.reward_xp,
            reward_coins=ach.reward_coins,
        )
        for ach in PREDEFINED_ACHIEVEMENTS
    ]


@app.get("/achievements/user/{user_id}", response_model=AchievementsResponse)
def get_user_achievements(user_id: int) -> AchievementsResponse:
    """Получить достижения пользователя с прогрессом."""
    from .domain.achievements import PREDEFINED_ACHIEVEMENTS, calculate_achievement_progress
    
    # Получаем пользователя и его статистику
    if USE_DB and db_mod.SessionLocal is not None:
        with db_mod.SessionLocal() as session:
            user_db = session.get(db_mod.UserDB, user_id)
            if not user_db:
                raise HTTPException(status_code=404, detail="User not found")
            
            skills_db = session.get(db_mod.SkillStatsDB, user_id)
            if not skills_db:
                raise HTTPException(status_code=404, detail="Skills not found")
            
            user = User(
                id=user_db.id,
                telegram_id=user_db.telegram_id,
                username=user_db.username,
                created_at=user_db.created_at,
                last_active_at=user_db.last_active_at,
                is_premium=user_db.is_premium,
            )
            
            skills = SkillStats(
                user_id=skills_db.user_id,
                memory_level=skills_db.memory_level,
                memory_xp=skills_db.memory_xp,
                reaction_level=skills_db.reaction_level,
                reaction_xp=skills_db.reaction_xp,
                daily_streak=skills_db.daily_streak,
                last_training_date=skills_db.last_training_date,
            )
            
            # Получаем разблокированные достижения
            unlocked = session.query(db_mod.UserAchievementDB).filter(
                db_mod.UserAchievementDB.user_id == user_id
            ).all()
            unlocked_ids = {ua.achievement_id for ua in unlocked}
            unlocked_map = {ua.achievement_id: ua for ua in unlocked}
            
            # Подсчитываем общее количество игр
            total_games = session.query(db_mod.GameSessionDB).filter(
                db_mod.GameSessionDB.user_id == user_id
            ).count()
    else:
        user = _users.get(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        skills = _get_skill_stats(user_id)
        unlocked_ids = set()
        unlocked_map = {}
        total_games = 0
    
    # Формируем список достижений с прогрессом
    achievements_out = []
    for ach in PREDEFINED_ACHIEVEMENTS:
        progress = calculate_achievement_progress(ach, user, skills, total_games)
        unlocked_data = unlocked_map.get(ach.id)
        
        achievements_out.append(
            AchievementOut(
                id=ach.id,
                name=ach.name,
                description=ach.description,
                category=ach.category.value,
                icon=ach.icon,
                rarity=ach.rarity.value,
                reward_xp=ach.reward_xp,
                reward_coins=ach.reward_coins,
                progress=progress if not unlocked_data else 1.0,
                unlocked_at=unlocked_data.unlocked_at if unlocked_data else None,
            )
        )
    
    return AchievementsResponse(
        achievements=achievements_out,
        total=len(PREDEFINED_ACHIEVEMENTS),
        unlocked_count=len(unlocked_ids),
    )


@app.get("/admin", response_class=HTMLResponse)
def admin_panel() -> str:
    """Админ-панель для управления пользователями и Premium подписками."""
    import os
    admin_html_path = os.path.join(os.path.dirname(__file__), "..", "admin.html")
    try:
        with open(admin_html_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Admin panel not found</h1>"


@app.get("/webapp", response_class=HTMLResponse)
def webapp() -> str:
    """
    Minimal Telegram WebApp page for the mini-app.
    Здесь реализована браузерная версия игры «Пары комариков»,
    которая ходит в backend за прогрессом и опытом.
    """
    return """
<!doctype html>
<html lang="ru">
  <head>
    <meta charset="utf-8" />
    <title>Комарики — мини-апп</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
      body {
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        margin: 0;
        padding: 16px;
        background: #020617;
        color: #f9fafb;
      }
      .wrapper {
        max-width: 480px;
        margin: 0 auto;
        padding: 16px;
      }
      h1 {
        font-size: 22px;
        margin: 0 0 4px;
      }
      .subtitle {
        font-size: 14px;
        color: #9ca3af;
        margin-bottom: 16px;
      }
      .panel {
        border-radius: 16px;
        background: #020617;
        border: 1px solid #111827;
        padding: 16px;
        box-shadow: 0 16px 40px rgba(0, 0, 0, 0.5);
        margin-bottom: 16px;
      }
      .stats {
        display: flex;
        justify-content: space-between;
        gap: 8px;
        font-size: 12px;
        color: #9ca3af;
        margin-bottom: 8px;
      }
      .stats span {
        display: block;
      }
      .game-switch {
        display: flex;
        gap: 8px;
        margin-bottom: 8px;
      }
      .game-switch button {
        flex: 1;
        padding: 6px 10px;
        border-radius: 999px;
        border: none;
        background: #111827;
        color: #e5e7eb;
        font-size: 13px;
        cursor: pointer;
      }
      .game-switch button.active {
        background: #4f46e5;
        color: #fff;
      }
      .board {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 8px;
        margin-top: 8px;
      }
      .tile {
        border-radius: 10px;
        background: #111827;
        aspect-ratio: 3 / 4;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 20px;
        cursor: pointer;
        border: 1px solid #1f2937;
        user-select: none;
        transition: transform 0.1s ease, background 0.1s ease, border-color 0.1s ease;
      }
      .tile:hover {
        transform: translateY(-1px);
        border-color: #4f46e5;
      }
      .tile.matched {
        background: #065f46;
        border-color: #10b981;
      }
      .tile.flipped {
        background: #1e293b;
      }
      .tile.seq-show {
        background: #4f46e5;
        border-color: #a5b4fc;
      }
      .tile.seq-correct {
        background: #065f46;
        border-color: #10b981;
      }
      .tile.seq-wrong {
        background: #7f1d1d;
        border-color: #f87171;
      }
      .controls {
        display: flex;
        gap: 8px;
        margin-top: 12px;
      }
      button {
        flex: 1;
        margin: 0;
        padding: 10px 14px;
        border-radius: 999px;
        border: none;
        background: #4f46e5;
        color: #fff;
        font-size: 14px;
        cursor: pointer;
      }
      button.secondary {
        background: #111827;
        color: #e5e7eb;
      }
      button:disabled {
        opacity: 0.5;
        cursor: default;
      }
      .log {
        font-size: 12px;
        color: #9ca3af;
        margin-top: 8px;
        min-height: 1.5em;
      }
      .progress-panel {
        margin-top: 16px;
      }
      .progress-header {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        margin-bottom: 8px;
      }
      .progress-header h2 {
        font-size: 16px;
        margin: 0;
      }
      .progress-subtitle {
        font-size: 12px;
        color: #9ca3af;
      }
      .progress-day {
        padding: 8px 0;
        border-top: 1px solid #111827;
      }
      .progress-day:first-child {
        border-top: none;
      }
      .progress-day-header {
        display: flex;
        justify-content: space-between;
        font-size: 12px;
        margin-bottom: 4px;
      }
      .progress-bars {
        display: flex;
        gap: 4px;
        margin-bottom: 4px;
      }
      .progress-bar {
        flex: 1;
        height: 6px;
        border-radius: 999px;
        background: #111827;
        overflow: hidden;
      }
      .progress-bar-inner {
        height: 100%;
        border-radius: 999px;
      }
      .progress-bar-inner.memory {
        background: #22c55e;
      }
      .progress-bar-inner.reaction {
        background: #38bdf8;
      }
      .progress-meta {
        font-size: 11px;
        color: #9ca3af;
      }
    </style>
  </head>
  <body>
    <div class="wrapper">
      <div class="panel">
        <h1>Комарики 🦟</h1>
        <div class="subtitle">Тренируй память в мини‑аппе: пары и маршруты.</div>

        <div class="game-switch">
          <button id="game-pairs-btn" class="active">Пары комариков</button>
          <button id="game-seq-btn" class="secondary">Маршрут комарика</button>
          <button id="game-react-btn" class="secondary">Охота за сигналом</button>
        </div>

        <div class="stats">
          <span id="user-info">Пользователь: ...</span>
          <span id="skill-info">Память: ? / Реакция: ?</span>
        </div>

        <div class="stats">
          <span id="moves-info">Ходы: 0</span>
          <span id="mistakes-info">Ошибки: 0</span>
          <span id="time-info">Время: 0 c</span>
        </div>

        <div id="board" class="board"></div>

        <div class="controls">
          <button id="start-btn">Играть заново</button>
          <button id="close-btn" class="secondary">Закрыть</button>
        </div>

        <div id="log" class="log"></div>
      </div>

      <div class="panel progress-panel">
        <div class="progress-header">
          <h2>Прогресс</h2>
          <div id="progress-summary" class="progress-subtitle">
            Загрузка прогресса...
          </div>
        </div>
        <div id="progress-list"></div>
      </div>
    </div>

    <script>
      const apiBase = "";

      const state = {
        currentGame: "pairs",
        userId: null,
        telegramId: null,
        username: null,
        sessionId: null,
        // Пары
        cards: [],
        flipped: [],
        matched: [],
        moves: 0,
        mistakes: 0,
        startTime: null,
        timerInterval: null,
        // Маршрут
        seqPoints: 6,
        seqSequence: [],
        seqUserInput: [],
        seqMaxLength: 0,
        seqTotalCorrect: 0,
        seqTotalMistakes: 0,
        seqActive: false,
        seqShowing: false,
        seqInputIndex: 0,
        // Охота за сигналом
        reactTotalRounds: 5,
        reactCompletedRounds: 0,
        reactCorrectHits: 0,
        reactMisses: 0,
        reactTimesMs: [],
        reactTarget: null,
        reactOptions: [],
        reactCorrectIndex: null,
        reactRoundStart: null,
        dailyLimitReached: false,
      };

      function shuffle(array) {
        for (let i = array.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1));
          [array[i], array[j]] = [array[j], array[i]];
        }
        return array;
      }

      function sleep(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
      }

      function renderBoard() {
        const board = document.getElementById("board");
        board.innerHTML = "";

        if (state.currentGame === "pairs") {
          state.cards.forEach((icon, index) => {
            const tile = document.createElement("div");
            tile.className = "tile";

            const idx = index;
            const isMatched = state.matched.includes(idx);
            const isFlipped = state.flipped.includes(idx);

            if (isMatched) tile.classList.add("matched");
            if (isFlipped) tile.classList.add("flipped");

            if (isMatched || isFlipped) {
              tile.textContent = icon;
            } else {
              tile.textContent = "❓";
            }

            tile.addEventListener("click", () => onPairsTileClick(idx));
            board.appendChild(tile);
          });
        } else if (state.currentGame === "sequence") {
          // 6 точек (1–6) для маршрута
          const total = state.seqPoints;
          for (let i = 0; i < total; i++) {
            const tile = document.createElement("div");
            tile.className = "tile";
            tile.textContent = String(i + 1);
            tile.addEventListener("click", () => onSequenceTileClick(i));
            board.appendChild(tile);
          }
        } else if (state.currentGame === "reaction") {
          // 3 варианта для реакции
          const options = state.reactOptions.length
            ? state.reactOptions
            : ["🧠", "⚡", "🦟"];
          for (let i = 0; i < options.length; i++) {
            const tile = document.createElement("div");
            tile.className = "tile";
            tile.textContent = options[i];
            tile.addEventListener("click", () => onReactionTileClick(i));
            board.appendChild(tile);
          }
        }
      }

      function updateStatsUI() {
        if (state.currentGame === "pairs") {
          document.getElementById("moves-info").textContent =
            "Ходы: " + state.moves;
          document.getElementById("mistakes-info").textContent =
            "Ошибки: " + state.mistakes;
          if (state.startTime) {
            const elapsedSec = Math.floor((Date.now() - state.startTime) / 1000);
            document.getElementById("time-info").textContent =
              "Время: " + elapsedSec + " c";
          } else {
            document.getElementById("time-info").textContent = "Время: 0 c";
          }
        } else if (state.currentGame === "sequence") {
          document.getElementById("moves-info").textContent =
            "Длина маршрута: " + state.seqSequence.length;
          document.getElementById("mistakes-info").textContent =
            "Ошибки (всего): " + state.seqTotalMistakes;
          document.getElementById("time-info").textContent = "";
        } else if (state.currentGame === "reaction") {
          document.getElementById("moves-info").textContent =
            "Раунды: " +
            state.reactCompletedRounds +
            " / " +
            state.reactTotalRounds;
          document.getElementById("mistakes-info").textContent =
            "Промахи: " + state.reactMisses;
          let avg = 0;
          if (state.reactTimesMs.length) {
            const sum = state.reactTimesMs.reduce((a, b) => a + b, 0);
            avg = Math.round(sum / state.reactTimesMs.length);
          }
          document.getElementById("time-info").textContent =
            "Сред. время: " + avg + " мс";
        }
      }

      function setLog(msg) {
        document.getElementById("log").textContent = msg || "";
      }

      function startTimer() {
        if (state.timerInterval) clearInterval(state.timerInterval);
        state.timerInterval = setInterval(updateStatsUI, 1000);
      }

      async function initUser() {
        try {
          let tgUserId = 0;
          let username = "demo";

          // Если мини‑апп открыт внутри Telegram — используем реального пользователя
          if (
            window.Telegram &&
            Telegram.WebApp &&
            Telegram.WebApp.initDataUnsafe &&
            Telegram.WebApp.initDataUnsafe.user
          ) {
            tgUserId = Telegram.WebApp.initDataUnsafe.user.id;
            username =
              Telegram.WebApp.initDataUnsafe.user.username || "user_" + tgUserId;

            state.telegramId = tgUserId;
            state.username = username;

            const resp = await fetch(apiBase + "/auth/telegram", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                telegram_id: tgUserId,
                username: username,
              }),
            });
            const data = await resp.json();
            state.userId = data.user.id;

            document.getElementById("user-info").textContent =
              "Пользователь: " + (state.username || "id " + state.telegramId);

            const skills = data.skills;
            document.getElementById("skill-info").textContent =
              "Память: " +
              skills.memory_level +
              " / Реакция: " +
              skills.reaction_level;
            await loadProgress();
          } else {
            // Обычный браузер: чистый демо‑режим без backend и лимитов
            state.telegramId = null;
            state.username = null;
            state.userId = null;
            document.getElementById("user-info").textContent =
              "Пользователь: демо режим (прогресс не сохраняется)";
            document.getElementById("skill-info").textContent =
              "Память / Реакция: демо";
          }
        } catch (e) {
          console.error(e);
          document.getElementById("user-info").textContent =
            "Пользователь: офлайн (демо режим)";
          setLog("Не удалось подключиться к backend. Можно играть в демо.");
        }
      }

      function switchGame(game) {
        if (state.currentGame === game) return;
        state.currentGame = game;
        document
          .getElementById("game-pairs-btn")
          .classList.toggle("active", game === "pairs");
        document
          .getElementById("game-seq-btn")
          .classList.toggle("active", game === "sequence");
        document
          .getElementById("game-react-btn")
          .classList.toggle("active", game === "reaction");

        // Сброс логов и статистики отображения
        setLog("");
        updateStatsUI();
        renderBoard();
      }

      async function startPairsGame() {
        state.currentGame = "pairs";
        document
          .getElementById("game-pairs-btn")
          .classList.add("active");
        document
          .getElementById("game-seq-btn")
          .classList.remove("active");
        document
          .getElementById("game-react-btn")
          .classList.remove("active");

        state.cards = [];
        state.flipped = [];
        state.matched = [];
        state.moves = 0;
        state.mistakes = 0;
        state.startTime = Date.now();
        updateStatsUI();
        startTimer();
        setLog("Игра началась! Ищи пары.");

        const baseIcons = ["🦟A", "🦟B", "🦟C", "🦟D", "🦟E", "🦟F"];
        state.cards = shuffle([...baseIcons, ...baseIcons]);

        renderBoard();

        state.sessionId = null;
        state.dailyLimitReached = false;
        if (state.userId != null) {
          try {
            const resp = await fetch(apiBase + "/game/session/start", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                user_id: state.userId,
                game_type: "memory_pairs",
                difficulty: "easy",
              }),
            });
            if (resp.ok) {
              const data = await resp.json();
              state.sessionId = data.session_id;
            } else {
              const err = await resp.json().catch(() => null);
              if (err && err.detail && err.detail.error === "daily_limit_exceeded") {
                state.dailyLimitReached = true;
                setLog(
                  "Лимит игр на сегодня исчерпан. Можно играть в демо, но XP не начисляется."
                );
              } else {
                setLog("Не удалось начать сессию на backend. Игра в демо.");
              }
            }
          } catch (e) {
            console.error(e);
            setLog("Не удалось связаться с backend. Игра в демо.");
          }
        }
      }

      function onPairsTileClick(idx) {
        if (state.currentGame !== "pairs") return;
        if (!state.cards.length) return;
        if (state.matched.includes(idx)) return;
        if (state.flipped.includes(idx)) return;
        if (state.flipped.length >= 2) return;

        state.flipped.push(idx);
        renderBoard();

        if (state.flipped.length === 2) {
          state.moves += 1;
          const [i1, i2] = state.flipped;
          const c1 = state.cards[i1];
          const c2 = state.cards[i2];

          if (c1 === c2) {
            state.matched.push(i1, i2);
            state.flipped = [];
            updateStatsUI();
            if (state.matched.length === state.cards.length) {
              finishPairsGame();
            }
          } else {
            state.mistakes += 1;
            updateStatsUI();
            setTimeout(() => {
              state.flipped = [];
              renderBoard();
            }, 700);
          }
        } else {
          updateStatsUI();
        }
      }

      async function finishPairsGame() {
        if (state.timerInterval) {
          clearInterval(state.timerInterval);
          state.timerInterval = null;
        }
        const elapsedMs = Date.now() - state.startTime;
        const result = {
          moves_count: state.moves,
          mistakes: state.mistakes,
          time_ms: elapsedMs,
        };

        if (state.dailyLimitReached) {
          setLog(
            "Лимит игр на сегодня исчерпан. Результат не сохранён, XP не начислен."
          );
          return;
        }

        if (state.userId != null && state.sessionId != null) {
          try {
            const resp = await fetch(apiBase + "/game/session/finish", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                session_id: state.sessionId,
                result: result,
              }),
            });
            const data = await resp.json();
            const gained = data.gained_xp;
            const skills = data.updated_skills;
            document.getElementById("skill-info").textContent =
              "Память: " +
              skills.memory_level +
              " / Реакция: " +
              skills.reaction_level;
            setLog(
              "Готово! Память +" +
                gained.memory_xp +
                ", Реакция +" +
                gained.reaction_xp +
                ". Серия дней: " +
                skills.daily_streak
            );
          } catch (e) {
            console.error(e);
            setLog("Игра завершена. Не удалось отправить результат на backend.");
          }
        } else {
          setLog("Игра завершена (демо). Результат не сохранён.");
        }
      }

      async function startSequenceGame() {
        state.currentGame = "sequence";
        if (state.timerInterval) {
          clearInterval(state.timerInterval);
          state.timerInterval = null;
        }

        document
          .getElementById("game-pairs-btn")
          .classList.remove("active");
        document
          .getElementById("game-seq-btn")
          .classList.add("active");
        document
          .getElementById("game-react-btn")
          .classList.remove("active");

        state.seqSequence = [];
        state.seqUserInput = [];
        state.seqMaxLength = 0;
        state.seqTotalCorrect = 0;
        state.seqTotalMistakes = 0;
        state.seqActive = true;
        state.seqShowing = false;
        state.seqInputIndex = 0;
        state.sessionId = null;
        state.dailyLimitReached = false;

        updateStatsUI();

        if (state.userId != null) {
          try {
            const resp = await fetch(apiBase + "/game/session/start", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                user_id: state.userId,
                game_type: "memory_sequence",
                difficulty: "easy",
              }),
            });
            if (resp.ok) {
              const data = await resp.json();
              state.sessionId = data.session_id;
            } else {
              const err = await resp.json().catch(() => null);
              if (err && err.detail && err.detail.error === "daily_limit_exceeded") {
                state.dailyLimitReached = true;
                setLog(
                  "Лимит игр на сегодня исчерпан. Можно играть в демо, но XP не начисляется."
                );
              } else {
                setLog("Не удалось начать сессию на backend. Игра в демо.");
              }
            }
          } catch (e) {
            console.error(e);
            setLog("Не удалось связаться с backend. Игра в демо.");
          }
        }

        // первый шаг маршрута и показ последовательности
        addSequenceStep();
        renderBoard();
        updateStatsUI();
        await playSequenceAnimation();
      }

      function addSequenceStep() {
        const next = Math.floor(Math.random() * state.seqPoints) + 1;
        state.seqSequence.push(next);
        state.seqMaxLength = Math.max(
          state.seqMaxLength,
          state.seqSequence.length
        );
      }

      async function playSequenceAnimation() {
        if (state.currentGame !== "sequence") return;
        if (!state.seqSequence.length) return;
        state.seqShowing = true;
        state.seqUserInput = [];
        state.seqInputIndex = 0;
        setLog("Смотри маршрут...");

        const board = document.getElementById("board");
        const tiles = Array.from(board.children);

        for (const point of state.seqSequence) {
          const idx = point - 1;
          const tile = tiles[idx];
          if (!tile) continue;
          tile.classList.add("seq-show");
          await sleep(500);
          tile.classList.remove("seq-show");
          await sleep(200);
        }

        state.seqShowing = false;
        setLog("Теперь повтори маршрут, нажимая по числам.");
      }

      function onSequenceTileClick(idx) {
        if (state.currentGame !== "sequence") return;
        if (!state.seqActive) return;
        if (state.seqShowing) return;
        if (!state.seqSequence.length) return;

        const point = idx + 1;
        const board = document.getElementById("board");
        const tiles = Array.from(board.children);
        const tile = tiles[idx];

        const expected = state.seqSequence[state.seqInputIndex] || null;

        if (point === expected) {
          state.seqTotalCorrect += 1;
          state.seqInputIndex += 1;
          if (tile) {
            tile.classList.add("seq-correct");
            setTimeout(() => tile.classList.remove("seq-correct"), 200);
          }

          if (state.seqInputIndex === state.seqSequence.length) {
            if (state.seqSequence.length >= 8) {
              finishSequenceGame(false);
            } else {
              addSequenceStep();
              renderBoard();
              updateStatsUI();
              setTimeout(() => {
                playSequenceAnimation();
              }, 400);
            }
          }
        } else {
          state.seqTotalMistakes += 1;
          if (tile) {
            tile.classList.add("seq-wrong");
            setTimeout(() => tile.classList.remove("seq-wrong"), 250);
          }
          setLog("Ошибка. Начинаем новый маршрут.");
          finishSequenceGame(true);
        }

        updateStatsUI();
      }

      async function finishSequenceGame(autoRestart) {
        state.seqActive = false;
        if (state.dailyLimitReached) {
          setLog(
            (document.getElementById("log").textContent || "") +
              " Лимит игр на сегодня исчерпан. Результат не сохранён."
          );
          return;
        }
        const result = {
          max_sequence_length: state.seqMaxLength,
          total_correct: state.seqTotalCorrect,
          total_mistakes: state.seqTotalMistakes,
        };

        if (state.userId != null && state.sessionId != null) {
          try {
            const resp = await fetch(apiBase + "/game/session/finish", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                session_id: state.sessionId,
                result: result,
              }),
            });
            const data = await resp.json();
            const gained = data.gained_xp;
            const skills = data.updated_skills;
            document.getElementById("skill-info").textContent =
              "Память: " +
              skills.memory_level +
              " / Реакция: " +
              skills.reaction_level;
            setLog(
              (document.getElementById("log").textContent || "") +
                " Память +" +
                gained.memory_xp +
                ", Реакция +" +
                gained.reaction_xp +
                ". Серия дней: " +
                skills.daily_streak
            );
          } catch (e) {
            console.error(e);
            setLog(
              (document.getElementById("log").textContent || "") +
                " Не удалось отправить результат на backend."
            );
          }
        } else {
          setLog(
            (document.getElementById("log").textContent || "") +
              " Результат не сохранён (демо)."
          );
        }

        if (autoRestart) {
          setTimeout(() => {
            startSequenceGame();
          }, 800);
        }
      }

      async function startReactionGame() {
        state.currentGame = "reaction";
        if (state.timerInterval) {
          clearInterval(state.timerInterval);
          state.timerInterval = null;
        }

        document
          .getElementById("game-pairs-btn")
          .classList.remove("active");
        document
          .getElementById("game-seq-btn")
          .classList.remove("active");
        document
          .getElementById("game-react-btn")
          .classList.add("active");

        state.reactCompletedRounds = 0;
        state.reactCorrectHits = 0;
        state.reactMisses = 0;
        state.reactTimesMs = [];
        state.reactTarget = null;
        state.reactOptions = [];
        state.reactCorrectIndex = null;
        state.reactRoundStart = null;
        state.sessionId = null;
        state.dailyLimitReached = false;

        updateStatsUI();

        if (state.userId != null) {
          try {
            const resp = await fetch(apiBase + "/game/session/start", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                user_id: state.userId,
                game_type: "reaction_hunt",
                difficulty: "easy",
              }),
            });
            if (resp.ok) {
              const data = await resp.json();
              state.sessionId = data.session_id;
            } else {
              const err = await resp.json().catch(() => null);
              if (err && err.detail && err.detail.error === "daily_limit_exceeded") {
                state.dailyLimitReached = true;
                setLog(
                  "Лимит игр на сегодня исчерпан. Можно играть в демо, но XP не начисляется."
                );
              } else {
                setLog("Не удалось начать сессию на backend. Игра в демо.");
              }
            }
          } catch (e) {
            console.error(e);
            setLog("Не удалось связаться с backend. Игра в демо.");
          }
        }

        startReactionRound();
      }

      function startReactionRound() {
        if (state.currentGame !== "reaction") return;
        if (state.reactCompletedRounds >= state.reactTotalRounds) {
          finishReactionGame();
          return;
        }

        const icons = ["🧠", "⚡", "🎯", "🌩", "🦟"];
        const target =
          icons[Math.floor(Math.random() * icons.length)];
        let options = shuffle([...icons]).slice(0, 3);
        if (!options.includes(target)) {
          options[Math.floor(Math.random() * options.length)] = target;
        }
        options = shuffle(options);

        state.reactTarget = target;
        state.reactOptions = options;
        state.reactCorrectIndex = options.indexOf(target);
        state.reactRoundStart = Date.now();

        setLog("Цель: " + target + ". Нажми на него как можно быстрее!");
        renderBoard();
        updateStatsUI();
      }

      function onReactionTileClick(idx) {
        if (state.currentGame !== "reaction") return;
        if (state.reactRoundStart == null) return;

        const board = document.getElementById("board");
        const tiles = Array.from(board.children);
        const tile = tiles[idx];

        const now = Date.now();
        const delta = now - state.reactRoundStart;
        const isCorrect = idx === state.reactCorrectIndex;

        if (isCorrect) {
          state.reactCorrectHits += 1;
          state.reactTimesMs.push(delta);
          if (tile) {
            tile.classList.add("seq-correct");
            setTimeout(() => tile.classList.remove("seq-correct"), 200);
          }
        } else {
          state.reactMisses += 1;
          if (tile) {
            tile.classList.add("seq-wrong");
            setTimeout(() => tile.classList.remove("seq-wrong"), 200);
          }
        }

        state.reactCompletedRounds += 1;
        state.reactRoundStart = null;

        if (state.reactCompletedRounds >= state.reactTotalRounds) {
          finishReactionGame();
        } else {
          setTimeout(() => {
            startReactionRound();
          }, 400);
        }

        updateStatsUI();
      }

      async function finishReactionGame() {
        if (state.dailyLimitReached) {
          setLog(
            "Лимит игр на сегодня исчерпан. Результат не сохранён, XP не начислен."
          );
          updateStatsUI();
          return;
        }

        let avgMs = 9999;
        if (state.reactTimesMs.length) {
          const sum = state.reactTimesMs.reduce((a, b) => a + b, 0);
          avgMs = Math.round(sum / state.reactTimesMs.length);
        }

        const result = {
          avg_reaction_ms: avgMs,
          correct_hits: state.reactCorrectHits,
          misses: state.reactMisses,
        };

        if (state.userId != null && state.sessionId != null) {
          try {
            const resp = await fetch(apiBase + "/game/session/finish", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                session_id: state.sessionId,
                result: result,
              }),
            });
            const data = await resp.json();
            const gained = data.gained_xp;
            const skills = data.updated_skills;
            document.getElementById("skill-info").textContent =
              "Память: " +
              skills.memory_level +
              " / Реакция: " +
              skills.reaction_level;
            setLog(
              "Игра завершена. Сред. время " +
                avgMs +
                " мс, попаданий " +
                state.reactCorrectHits +
                ", промахов " +
                state.reactMisses +
                ". Память +" +
                gained.memory_xp +
                ", Реакция +" +
                gained.reaction_xp +
                ". Серия дней: " +
                skills.daily_streak
            );
          } catch (e) {
            console.error(e);
            setLog(
              "Игра завершена. Не удалось отправить результат на backend."
            );
          }
        } else {
          setLog("Игра завершена (демо). Результат не сохранён.");
        }

        updateStatsUI();
      }

      function initButtons() {
        document.getElementById("start-btn").addEventListener("click", () => {
          if (state.currentGame === "pairs") {
            startPairsGame();
          } else if (state.currentGame === "sequence") {
            startSequenceGame();
          } else {
            startReactionGame();
          }
        });

        document
          .getElementById("close-btn")
          .addEventListener("click", () => {
            if (window.Telegram && Telegram.WebApp) {
              Telegram.WebApp.close();
            } else {
              window.close();
            }
          });

        document
          .getElementById("game-pairs-btn")
          .addEventListener("click", () => {
            switchGame("pairs");
          });
        document
          .getElementById("game-seq-btn")
          .addEventListener("click", () => {
            switchGame("sequence");
          });
        document
          .getElementById("game-react-btn")
          .addEventListener("click", () => {
            switchGame("reaction");
          });
      }

      window.addEventListener("load", () => {
        initButtons();
        initUser().then(() => {
          startPairsGame();
        });
      });

      async function loadProgress() {
        if (!state.userId) return;
        const summaryEl = document.getElementById("progress-summary");
        const listEl = document.getElementById("progress-list");
        if (!summaryEl || !listEl) return;

        try {
          const resp = await fetch(
            apiBase + "/progress/history?user_id=" + state.userId + "&days=14"
          );
          if (!resp.ok) {
            summaryEl.textContent = "Не удалось загрузить прогресс.";
            return;
          }
          const data = await resp.json();
          const skills = data.skills;
          const user = data.user || {};
          const isPremium = !!user.is_premium;

          let summary =
            "Память " +
            skills.memory_level +
            " (XP " +
            skills.memory_xp +
            "/" +
            skills.memory_xp_to_next +
            "), Реакция " +
            skills.reaction_level +
            " (XP " +
            skills.reaction_xp +
            "/" +
            skills.reaction_xp_to_next +
            "). Серия дней: " +
            skills.daily_streak;

          const FREE_LIMIT = """ + str(FREE_DAILY_GAMES_LIMIT) + """;
          let todayGames = 0;
          if (data.days && data.days.length) {
            const today = new Date();
            const ty = today.getFullYear();
            const tm = today.getMonth();
            const td = today.getDate();
            for (const d of data.days) {
              const dt = new Date(d.date);
              if (
                dt.getFullYear() === ty &&
                dt.getMonth() === tm &&
                dt.getDate() === td
              ) {
                todayGames = d.games_count || 0;
                break;
              }
            }
          }

          if (isPremium) {
            summary += " • Премиум: безлимит игр и повышенный XP.";
          } else {
            summary +=
              " • Бесплатный лимит: " +
              FREE_LIMIT +
              " игр/день, сегодня сыграно: " +
              todayGames +
              ".";
          }

          summaryEl.textContent = summary;

          listEl.innerHTML = "";
          if (!data.days || !data.days.length) {
            const empty = document.createElement("div");
            empty.className = "progress-subtitle";
            empty.textContent = "Пока нет сыгранных игр за последние 14 дней.";
            listEl.appendChild(empty);
            return;
          }

          const maxXp = data.days.reduce(
            (acc, d) => Math.max(acc, d.memory_xp, d.reaction_xp),
            1
          );

          data.days.forEach((d) => {
            const dayEl = document.createElement("div");
            dayEl.className = "progress-day";

            const headerEl = document.createElement("div");
            headerEl.className = "progress-day-header";
            const dateObj = new Date(d.date);
            const dateStr =
              ("0" + dateObj.getDate()).slice(0, 2) +
              "." +
              ("0" + (dateObj.getMonth() + 1)).slice(0, 2);
            headerEl.innerHTML =
              '<span>' +
              dateStr +
              "</span><span>Игр: " +
              d.games_count +
              "</span>";
            dayEl.appendChild(headerEl);

            const barsEl = document.createElement("div");
            barsEl.className = "progress-bars";

            const memBar = document.createElement("div");
            memBar.className = "progress-bar";
            const memInner = document.createElement("div");
            memInner.className = "progress-bar-inner memory";
            const memPct =
              maxXp > 0 ? Math.max(4, Math.round((d.memory_xp / maxXp) * 100)) : 0;
            memInner.style.width = memPct + "%";
            memBar.appendChild(memInner);

            const reactBar = document.createElement("div");
            reactBar.className = "progress-bar";
            const reactInner = document.createElement("div");
            reactInner.className = "progress-bar-inner reaction";
            const reactPct =
              maxXp > 0
                ? Math.max(4, Math.round((d.reaction_xp / maxXp) * 100))
                : 0;
            reactInner.style.width = reactPct + "%";
            reactBar.appendChild(reactInner);

            barsEl.appendChild(memBar);
            barsEl.appendChild(reactBar);
            dayEl.appendChild(barsEl);

            const metaEl = document.createElement("div");
            metaEl.className = "progress-meta";
            const pieces = [];
            if (d.memory_xp) {
              pieces.push("XP памяти: " + d.memory_xp);
            }
            if (d.reaction_xp) {
              pieces.push("XP реакции: " + d.reaction_xp);
            }
            if (d.avg_reaction_ms != null) {
              pieces.push("Сред. реакция: " + Math.round(d.avg_reaction_ms) + " мс");
            }
            if (d.best_sequence_length != null) {
              pieces.push("Маршрут до " + d.best_sequence_length + " шагов");
            }
            metaEl.textContent = pieces.join(" • ");
            dayEl.appendChild(metaEl);

            listEl.appendChild(dayEl);
          });
        } catch (e) {
          console.error(e);
          summaryEl.textContent = "Ошибка загрузки прогресса.";
        }
      }
    </script>
  </body>
</html>
    """
