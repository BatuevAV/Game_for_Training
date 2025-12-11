"""
Database configuration and ORM models for the 'Комарики' app.

The database URL is taken from the `DATABASE_URL` environment variable.
Example for PostgreSQL:
  postgresql+psycopg2://user:password@localhost:5432/komariki

If `DATABASE_URL` is not set, the API falls back to in-memory storage.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    create_engine,
    JSON,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .domain.models import GameType, Rarity, Skill


DATABASE_URL = os.getenv("DATABASE_URL")


class Base(DeclarativeBase):
    pass


class UserDB(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SkillStatsDB(Base):
    __tablename__ = "skill_stats"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), primary_key=True
    )
    memory_level: Mapped[int] = mapped_column(Integer, default=1)
    memory_xp: Mapped[int] = mapped_column(Integer, default=0)
    reaction_level: Mapped[int] = mapped_column(Integer, default=1)
    reaction_xp: Mapped[int] = mapped_column(Integer, default=0)
    daily_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_training_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)


class MosquitoTypeDB(Base):
    __tablename__ = "mosquito_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    rarity: Mapped[Rarity] = mapped_column(Enum(Rarity), nullable=False)
    focus_skill: Mapped[Skill] = mapped_column(Enum(Skill), nullable=False)
    icon_url: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String(512), default="")


class UserMosquitoDB(Base):
    __tablename__ = "user_mosquitoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    mosquito_type_id: Mapped[int] = mapped_column(Integer, ForeignKey("mosquito_types.id"))
    level: Mapped[int] = mapped_column(Integer, default=1)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    obtained_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    source: Mapped[str] = mapped_column(String(255), default="")


class GameSessionDB(Base):
    __tablename__ = "game_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    game_type: Mapped[GameType] = mapped_column(Enum(GameType), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    gained_memory_xp: Mapped[int] = mapped_column(Integer, default=0)
    gained_reaction_xp: Mapped[int] = mapped_column(Integer, default=0)
    performance_score: Mapped[float] = mapped_column(Integer, default=0)


engine = create_engine(DATABASE_URL) if DATABASE_URL else None
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False) if engine else None


def init_db() -> None:
    if engine is None:
        return
    Base.metadata.create_all(engine)

