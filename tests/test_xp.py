from testik.domain.models import GameType
from testik.domain.xp import (
    compute_xp_for_game,
    performance_memory_pairs,
    performance_memory_sequence,
    performance_reaction_hunt,
    skill_xp_to_next,
    streak_multiplier,
)


def test_skill_xp_to_next_progression():
    assert skill_xp_to_next(1) == 40
    assert skill_xp_to_next(2) == 55
    assert skill_xp_to_next(10) == 40 + 15 * 9
    # level 11 switches formula but stays continuous
    assert skill_xp_to_next(11) == 175
    assert skill_xp_to_next(12) == 195


def test_streak_multiplier_bounds():
    assert streak_multiplier(0) == 1.0
    assert streak_multiplier(1) == 1.0
    assert streak_multiplier(2) == 1.1
    assert streak_multiplier(3) == 1.2
    assert streak_multiplier(4) == 1.3
    assert streak_multiplier(5) == 1.4
    # 6 and more are capped at 1.5
    assert streak_multiplier(6) == 1.5
    assert streak_multiplier(10) == 1.5


def test_performance_memory_pairs_good_and_bad():
    good = {
        "moves_count": 20,
        "mistakes": 2,
        "time_ms": 45_000,
    }
    bad = {
        "moves_count": 40,
        "mistakes": 20,
        "time_ms": 180_000,
    }

    good_score = performance_memory_pairs(good, optimal_time_sec=60)
    bad_score = performance_memory_pairs(bad, optimal_time_sec=60)

    assert 0.0 <= bad_score < good_score <= 1.0


def test_performance_memory_sequence():
    strong = {
        "max_sequence_length": 12,
        "total_correct": 30,
        "total_mistakes": 2,
    }
    weak = {
        "max_sequence_length": 3,
        "total_correct": 5,
        "total_mistakes": 10,
    }
    strong_score = performance_memory_sequence(strong, target_length=8)
    weak_score = performance_memory_sequence(weak, target_length=8)

    assert 0.0 <= weak_score < strong_score <= 1.0


def test_performance_memory_sequence_handles_missing_fields():
    # Should not raise even if fields are missing
    partial = {}
    score = performance_memory_sequence(partial, target_length=8)
    assert 0.0 <= score <= 1.0


def test_performance_reaction_hunt():
    fast = {
        "avg_reaction_ms": 320,
        "correct_hits": 25,
        "misses": 2,
    }
    slow = {
        "avg_reaction_ms": 800,
        "correct_hits": 5,
        "misses": 15,
    }
    fast_score = performance_reaction_hunt(fast)
    slow_score = performance_reaction_hunt(slow)

    assert 0.0 <= slow_score < fast_score <= 1.0


def test_compute_xp_for_memory_game_primary_skill_gets_more_xp():
    result = {
        "moves_count": 20,
        "mistakes": 2,
        "time_ms": 50_000,
    }
    xp_gain = compute_xp_for_game(
        GameType.MEMORY_PAIRS,
        result=result,
        daily_streak=3,
        optimal_time_sec=60,
    )

    assert xp_gain.memory_xp > xp_gain.reaction_xp
    assert xp_gain.performance_score > 0.0


def test_compute_xp_for_reaction_game_primary_skill_gets_more_xp():
    result = {
        "avg_reaction_ms": 350,
        "correct_hits": 20,
        "misses": 1,
    }
    xp_gain = compute_xp_for_game(
        GameType.REACTION_HUNT,
        result=result,
        daily_streak=2,
    )

    assert xp_gain.reaction_xp > xp_gain.memory_xp
    assert xp_gain.performance_score > 0.0
