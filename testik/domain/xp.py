from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .models import (
    GameType,
    MemoryPairsResult,
    MemorySequenceResult,
    ReactionHuntResult,
)


def clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(max_value, value))


def skill_xp_to_next(level: int) -> int:
    """
    XP required to reach the next skill level.

    Levels 1–10: 40 + 15*(level-1)
    Levels 11–30: 175 + 20*(level-10)
    Above 30: extend same progression as 11–30.
    """
    if level < 1:
        raise ValueError("level must be >= 1")
    if level <= 10:
        return 40 + 15 * (level - 1)
    # 11–30 and above: keep progression continuous with level 10
    return 175 + 20 * (level - 11)


def streak_multiplier(daily_streak: int) -> float:
    if daily_streak <= 1:
        return 1.0
    if daily_streak == 2:
        return 1.1
    if daily_streak == 3:
        return 1.2
    if daily_streak == 4:
        return 1.3
    if daily_streak == 5:
        return 1.4
    return 1.5


def performance_memory_pairs(result: MemoryPairsResult, optimal_time_sec: int) -> float:
    moves_count = max(result["moves_count"], 1)
    mistakes = max(result["mistakes"], 0)
    time_sec = max(result["time_ms"], 1) / 1000.0

    mistake_rate = mistakes / moves_count

    # Time score: 1.0 at optimal_time_sec, 0.0 at 3x optimal or worse
    slow_time = optimal_time_sec * 3
    if time_sec <= optimal_time_sec:
        time_score = 1.0
    elif time_sec >= slow_time:
        time_score = 0.0
    else:
        time_score = (slow_time - time_sec) / (slow_time - optimal_time_sec)

    # Mistake score: 1.0 at <=0.1, 0.5 at ~0.3, 0.0 at >=0.6
    if mistake_rate <= 0.1:
        mistake_score = 1.0
    elif mistake_rate >= 0.6:
        mistake_score = 0.0
    elif mistake_rate <= 0.3:
        # interpolate between 1.0 and 0.5
        mistake_score = 1.0 - (mistake_rate - 0.1) / (0.3 - 0.1) * 0.5
    else:
        # interpolate between 0.5 and 0.0
        mistake_score = 0.5 - (mistake_rate - 0.3) / (0.6 - 0.3) * 0.5

    return clamp(0.5 * time_score + 0.5 * mistake_score)


def performance_memory_sequence(
    result: MemorySequenceResult, target_length: int
) -> float:
    # Use .get with defaults to be robust against incomplete payloads
    max_len = max(int(result.get("max_sequence_length", 0) or 0), 0)
    total_correct = max(int(result.get("total_correct", 0) or 0), 0)
    total_mistakes = max(int(result.get("total_mistakes", 0) or 0), 0)

    length_score_raw = max_len / max(target_length, 1)
    length_score = clamp(length_score_raw / 1.5)

    total_attempts = total_correct + total_mistakes
    if total_attempts == 0:
        accuracy = 0.0
    else:
        accuracy = total_correct / total_attempts

    return clamp(0.7 * length_score + 0.3 * accuracy)


def performance_reaction_hunt(
    result: ReactionHuntResult, fast_ms: int = 350, slow_ms: int = 700
) -> float:
    avg_ms = max(result["avg_reaction_ms"], 1)
    correct = max(result["correct_hits"], 0)
    misses = max(result["misses"], 0)

    if avg_ms <= fast_ms:
        reaction_score = 1.0
    elif avg_ms >= slow_ms:
        reaction_score = 0.0
    else:
        reaction_score = (slow_ms - avg_ms) / (slow_ms - fast_ms)

    total = correct + misses
    if total == 0:
        accuracy_score = 0.0
    else:
        accuracy = correct / total
        if accuracy >= 0.9:
            accuracy_score = 1.0
        elif accuracy <= 0.4:
            accuracy_score = 0.0
        elif accuracy >= 0.7:
            # between 0.7 and 0.9 → 0.5–1.0
            accuracy_score = 0.5 + (accuracy - 0.7) / (0.9 - 0.7) * 0.5
        else:
            # between 0.4 and 0.7 → 0.0–0.5
            accuracy_score = (accuracy - 0.4) / (0.7 - 0.4) * 0.5

    return clamp(0.6 * reaction_score + 0.4 * accuracy_score)


@dataclass
class XpGain:
    memory_xp: int
    reaction_xp: int
    performance_score: float


def compute_xp_for_game(
    game_type: GameType,
    result: dict,
    daily_streak: int,
    optimal_time_sec: int = 60,
    target_length: int = 8,
) -> XpGain:
    """
    Compute XP for a finished game session according to the rules
    described in the specification.
    """
    if game_type == GameType.MEMORY_PAIRS:
        perf = performance_memory_pairs(result, optimal_time_sec)
        memory_ratio, reaction_ratio = 0.9, 0.1
    elif game_type == GameType.MEMORY_SEQUENCE:
        perf = performance_memory_sequence(result, target_length)
        memory_ratio, reaction_ratio = 0.9, 0.1
    elif game_type == GameType.REACTION_HUNT:
        perf = performance_reaction_hunt(result)
        memory_ratio, reaction_ratio = 0.1, 0.9
    else:
        raise ValueError(f"Unsupported game type: {game_type}")

    base_xp = 15
    bonus_xp = 25
    raw_xp = base_xp + bonus_xp * perf

    mult = streak_multiplier(daily_streak)
    total_xp = int(round(raw_xp * mult))

    memory_xp = int(round(total_xp * memory_ratio))
    reaction_xp = int(round(total_xp * reaction_ratio))

    # ensure at least 1 XP goes to the primary skill
    if game_type in (GameType.MEMORY_PAIRS, GameType.MEMORY_SEQUENCE):
        if memory_xp == 0 and total_xp > 0:
            memory_xp = 1
    else:
        if reaction_xp == 0 and total_xp > 0:
            reaction_xp = 1

    return XpGain(memory_xp=memory_xp, reaction_xp=reaction_xp, performance_score=perf)
