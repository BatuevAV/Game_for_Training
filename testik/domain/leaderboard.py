"""
Leaderboard system for ranking players.

Provides different ranking types:
- By total XP
- By memory skill level
- By reaction skill level
- By total games played
- By current streak

Time periods:
- All time
- Weekly
- Monthly
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from ..db import UserDB, GameSessionDB


class LeaderboardType(str, Enum):
    """Type of leaderboard ranking."""
    TOTAL_XP = "total_xp"
    MEMORY_LEVEL = "memory_level"
    REACTION_LEVEL = "reaction_level"
    GAMES_PLAYED = "games_played"
    CURRENT_STREAK = "current_streak"


class TimePeriod(str, Enum):
    """Time period for leaderboard filtering."""
    ALL_TIME = "all_time"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass
class LeaderboardEntry:
    """Single entry in a leaderboard."""
    rank: int
    user_id: int
    telegram_id: int
    username: Optional[str]
    first_name: Optional[str]
    value: int  # The metric value (XP, level, games count, etc.)
    is_premium: bool


def get_leaderboard(
    session: Session,
    leaderboard_type: LeaderboardType,
    time_period: TimePeriod = TimePeriod.ALL_TIME,
    limit: int = 100,
    user_id: Optional[int] = None
) -> List[LeaderboardEntry]:
    """
    Get leaderboard rankings.
    
    Args:
        session: Database session
        leaderboard_type: Type of ranking
        time_period: Time period filter
        limit: Maximum number of entries to return
        user_id: Optional user ID to include in results even if not in top
        
    Returns:
        List of leaderboard entries with rankings
    """
    # Calculate time filter if needed
    time_filter = None
    if time_period == TimePeriod.WEEKLY:
        week_ago = datetime.utcnow() - timedelta(days=7)
        time_filter = GameSessionDB.finished_at >= week_ago
    elif time_period == TimePeriod.MONTHLY:
        month_ago = datetime.utcnow() - timedelta(days=30)
        time_filter = GameSessionDB.finished_at >= month_ago
    
    # Build query based on leaderboard type
    if leaderboard_type == LeaderboardType.TOTAL_XP:
        query = select(
            UserDB.id,
            UserDB.telegram_id,
            UserDB.username,
            UserDB.first_name,
            UserDB.total_xp.label('value'),
            UserDB.is_premium
        ).order_by(UserDB.total_xp.desc())
        
    elif leaderboard_type == LeaderboardType.MEMORY_LEVEL:
        query = select(
            UserDB.id,
            UserDB.telegram_id,
            UserDB.username,
            UserDB.first_name,
            UserDB.memory_level.label('value'),
            UserDB.is_premium
        ).order_by(UserDB.memory_level.desc(), UserDB.memory_xp.desc())
        
    elif leaderboard_type == LeaderboardType.REACTION_LEVEL:
        query = select(
            UserDB.id,
            UserDB.telegram_id,
            UserDB.username,
            UserDB.first_name,
            UserDB.reaction_level.label('value'),
            UserDB.is_premium
        ).order_by(UserDB.reaction_level.desc(), UserDB.reaction_xp.desc())
        
    elif leaderboard_type == LeaderboardType.CURRENT_STREAK:
        query = select(
            UserDB.id,
            UserDB.telegram_id,
            UserDB.username,
            UserDB.first_name,
            UserDB.current_streak.label('value'),
            UserDB.is_premium
        ).order_by(UserDB.current_streak.desc())
        
    elif leaderboard_type == LeaderboardType.GAMES_PLAYED:
        # For time-filtered games count, we need to aggregate from sessions
        if time_filter is not None:
            query = (
                select(
                    UserDB.id,
                    UserDB.telegram_id,
                    UserDB.username,
                    UserDB.first_name,
                    func.count(GameSessionDB.id).label('value'),
                    UserDB.is_premium
                )
                .join(GameSessionDB, UserDB.id == GameSessionDB.user_id)
                .where(time_filter)
                .group_by(
                    UserDB.id,
                    UserDB.telegram_id,
                    UserDB.username,
                    UserDB.first_name,
                    UserDB.is_premium
                )
                .order_by(func.count(GameSessionDB.id).desc())
            )
        else:
            query = select(
                UserDB.id,
                UserDB.telegram_id,
                UserDB.username,
                UserDB.first_name,
                UserDB.games_played.label('value'),
                UserDB.is_premium
            ).order_by(UserDB.games_played.desc())
    
    # Execute query with limit
    results = session.execute(query.limit(limit)).all()
    
    # Convert to leaderboard entries with ranks
    entries = []
    for rank, row in enumerate(results, start=1):
        entries.append(LeaderboardEntry(
            rank=rank,
            user_id=row.id,
            telegram_id=row.telegram_id,
            username=row.username,
            first_name=row.first_name,
            value=row.value,
            is_premium=row.is_premium
        ))
    
    # If user_id is provided and not in top results, add their position
    if user_id is not None:
        user_in_top = any(entry.user_id == user_id for entry in entries)
        if not user_in_top:
            user_entry = _get_user_rank(
                session,
                user_id,
                leaderboard_type,
                time_filter
            )
            if user_entry:
                entries.append(user_entry)
    
    return entries


def _get_user_rank(
    session: Session,
    user_id: int,
    leaderboard_type: LeaderboardType,
    time_filter: Optional[any]
) -> Optional[LeaderboardEntry]:
    """Get specific user's rank in leaderboard."""
    # Get user data
    user = session.get(UserDB, user_id)
    if not user:
        return None
    
    # Count users ranked higher
    if leaderboard_type == LeaderboardType.TOTAL_XP:
        rank_query = select(func.count()).where(UserDB.total_xp > user.total_xp)
        value = user.total_xp
        
    elif leaderboard_type == LeaderboardType.MEMORY_LEVEL:
        rank_query = select(func.count()).where(
            (UserDB.memory_level > user.memory_level) |
            ((UserDB.memory_level == user.memory_level) & (UserDB.memory_xp > user.memory_xp))
        )
        value = user.memory_level
        
    elif leaderboard_type == LeaderboardType.REACTION_LEVEL:
        rank_query = select(func.count()).where(
            (UserDB.reaction_level > user.reaction_level) |
            ((UserDB.reaction_level == user.reaction_level) & (UserDB.reaction_xp > user.reaction_xp))
        )
        value = user.reaction_level
        
    elif leaderboard_type == LeaderboardType.CURRENT_STREAK:
        rank_query = select(func.count()).where(UserDB.current_streak > user.current_streak)
        value = user.current_streak
        
    elif leaderboard_type == LeaderboardType.GAMES_PLAYED:
        if time_filter is not None:
            # Count user's games in period
            user_games = session.execute(
                select(func.count())
                .select_from(GameSessionDB)
                .where(and_(GameSessionDB.user_id == user_id, time_filter))
            ).scalar()
            value = user_games
            
            # Count users with more games in period
            rank_query = (
                select(func.count(func.distinct(GameSessionDB.user_id)))
                .select_from(GameSessionDB)
                .where(time_filter)
                .group_by(GameSessionDB.user_id)
                .having(func.count(GameSessionDB.id) > value)
            )
        else:
            rank_query = select(func.count()).where(UserDB.games_played > user.games_played)
            value = user.games_played
    
    rank = session.execute(rank_query).scalar() + 1
    
    return LeaderboardEntry(
        rank=rank,
        user_id=user.id,
        telegram_id=user.telegram_id,
        username=user.username,
        first_name=user.first_name,
        value=value,
        is_premium=user.is_premium
    )
