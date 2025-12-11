"""
Minimal Telegram bot skeleton for the 'Комарики' brain-training app.

This file does not implement full game flows yet, but provides:
- /start handler
- simple menu with buttons for the three core games

Domain logic for XP and models lives in testik.domain.
"""

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from dotenv import load_dotenv

from .domain.models import GameType
from .domain.xp import compute_xp_for_game


BOT_TOKEN_ENV = "BOT_TOKEN"
BACKEND_URL_ENV = "BACKEND_URL"
WEBAPP_URL_ENV = "WEBAPP_URL"


# Load environment variables from .env if present
load_dotenv()

BACKEND_URL = os.getenv(BACKEND_URL_ENV, "http://127.0.0.1:8000")
WEBAPP_URL = os.getenv(WEBAPP_URL_ENV, f"{BACKEND_URL}/webapp")

# Telegram WebApp URLs must be HTTPS. For local development (http://127.0.0.1)
# we disable the mini-app button to avoid TelegramBadRequest.
if WEBAPP_URL and not WEBAPP_URL.startswith("https://"):
    WEBAPP_URL = None


def build_main_keyboard() -> ReplyKeyboardMarkup:
    buttons_row1 = [
        KeyboardButton(text="🎴 Пары комариков"),
        KeyboardButton(text="🧠 Маршрут комарика"),
    ]
    buttons_row2 = [KeyboardButton(text="⚡ Охота за сигналом")]

    if WEBAPP_URL:
        buttons_row3 = [
            KeyboardButton(
                text="🌐 Открыть мини-апп",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        ]
        keyboard = [buttons_row1, buttons_row2, buttons_row3]
    else:
        keyboard = [buttons_row1, buttons_row2]

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


async def handle_start(message: Message) -> None:
    kb = build_main_keyboard()
    await message.answer(
        (
            "Привет! Я бот-тренажёр для развития памяти и скорости реакции.\n\n"
            "Выбирай игру ниже, чтобы потренироваться с комариками.\n\n"
            "Игры работают внутри чата, с простыми текстовыми полями и эмодзи.\n"
            "Если запущен backend (FastAPI), прогресс и опыт будут сохраняться."
        ),
        reply_markup=kb,
    )


async def handle_game_choice(message: Message) -> None:
    text = message.text or ""
    if "Пары комариков" in text:
        await start_memory_pairs_game(message)
        return
    elif "Маршрут комарика" in text:
        await start_memory_sequence_game(message)
        return
    elif "Охота за сигналом" in text:
        await start_reaction_hunt_game(message)
        return
    else:
        reply = "Пока понимаю только выбор игр с клавиатуры ниже."

    await message.answer(reply)


# --- In-chat game state and logic ---


@dataclass
class MemoryPairsState:
    cards: List[str]
    matched: List[int] = field(default_factory=list)
    moves_count: int = 0
    mistakes: int = 0
    started_at: float = field(default_factory=time.monotonic)
    backend_session_id: Optional[int] = None


@dataclass
class MemorySequenceState:
    points: int
    sequence: List[int] = field(default_factory=list)
    max_sequence_length: int = 0
    total_correct: int = 0
    total_mistakes: int = 0
    active: bool = True
    backend_session_id: Optional[int] = None


@dataclass
class ReactionRound:
    target: str
    options: List[str]
    correct_index: int
    start_time: float


@dataclass
class ReactionHuntState:
    total_rounds: int = 5
    current_round: Optional[ReactionRound] = None
    completed_rounds: int = 0
    correct_hits: int = 0
    misses: int = 0
    reaction_times_ms: List[float] = field(default_factory=list)
    backend_session_id: Optional[int] = None


MEMORY_PAIRS_GAMES: Dict[int, MemoryPairsState] = {}
MEMORY_SEQUENCE_GAMES: Dict[int, MemorySequenceState] = {}
REACTION_HUNT_GAMES: Dict[int, ReactionHuntState] = {}


def _clear_user_games(user_id: int) -> None:
    MEMORY_PAIRS_GAMES.pop(user_id, None)
    MEMORY_SEQUENCE_GAMES.pop(user_id, None)
    REACTION_HUNT_GAMES.pop(user_id, None)


async def _backend_start_session_for_user(
    message: Message,
    game_type: GameType,
) -> Optional[int]:
    if not BACKEND_URL:
        return None

    try:
        async with httpx.AsyncClient(
            base_url=BACKEND_URL,
            timeout=5.0,
        ) as client:
            auth_payload = {
                "telegram_id": message.from_user.id,
                "username": message.from_user.username,
            }
            auth_resp = await client.post("/auth/telegram", json=auth_payload)
            auth_resp.raise_for_status()
            auth_data = auth_resp.json()
            user_id = auth_data["user"]["id"]

            start_payload = {
                "user_id": user_id,
                "game_type": game_type.value,
                "difficulty": "easy",
            }
            start_resp = await client.post(
                "/game/session/start",
                json=start_payload,
            )
            start_resp.raise_for_status()
            start_data = start_resp.json()
            return int(start_data["session_id"])
    except httpx.HTTPError:
        return None


async def _backend_finish_session(
    session_id: int,
    result: dict,
) -> Optional[dict]:
    if not BACKEND_URL:
        return None

    try:
        async with httpx.AsyncClient(
            base_url=BACKEND_URL,
            timeout=5.0,
        ) as client:
            resp = await client.post(
                "/game/session/finish",
                json={"session_id": session_id, "result": result},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError:
        return None


def _render_memory_pairs_board(state: MemoryPairsState) -> str:
    cells = []
    for idx, icon in enumerate(state.cards, start=1):
        if idx in state.matched:
            cell = icon
        else:
            cell = "❓"
        cells.append(f"{idx:2d}:{cell}")

    # format as 4 columns (3x4 grid)
    lines = []
    for i in range(0, len(cells), 4):
        lines.append("  ".join(cells[i : i + 4]))

    header = (
        f"Пары комариков\n"
        f"Ходы: {state.moves_count} | Ошибки: {state.mistakes}\n\n"
        "Выбери две карточки и введи их номера через пробел, например: `3 7`."
    )
    return header + "\n\n" + "\n".join(lines)


async def start_memory_pairs_game(message: Message) -> None:
    user_id = message.from_user.id
    _clear_user_games(user_id)

    # 3x4 = 12 карточек, 6 пар
    base_icons = ["🦟A", "🦟B", "🦟C", "🦟D", "🦟E", "🦟F"]
    cards = base_icons * 2
    random.shuffle(cards)

    state = MemoryPairsState(cards=cards)
    MEMORY_PAIRS_GAMES[user_id] = state

    # Try to start backend session (optional)
    session_id = await _backend_start_session_for_user(
        message,
        GameType.MEMORY_PAIRS,
    )
    state.backend_session_id = session_id

    await message.answer(
        "Начинаем игру «Пары комариков»! Найди все пары как можно быстрее.",
        parse_mode="Markdown",
    )
    await message.answer(_render_memory_pairs_board(state), parse_mode="Markdown")


async def handle_memory_pairs_move(message: Message) -> None:
    user_id = message.from_user.id
    state = MEMORY_PAIRS_GAMES.get(user_id)
    if not state:
        return

    text = (message.text or "").strip()
    parts = text.split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        await message.answer("Нужно ввести два номера карточек, например: `3 7`.", parse_mode="Markdown")
        return

    i1, i2 = map(int, parts)
    if i1 == i2:
        await message.answer("Нужно выбрать две разные карточки.")
        return

    max_index = len(state.cards)
    if not (1 <= i1 <= max_index and 1 <= i2 <= max_index):
        await message.answer(f"Номера должны быть от 1 до {max_index}.")
        return

    if i1 in state.matched or i2 in state.matched:
        await message.answer("Эти карточки уже найдены как пара.")
        return

    state.moves_count += 1

    card1 = state.cards[i1 - 1]
    card2 = state.cards[i2 - 1]
    if card1 == card2:
        state.matched.extend([i1, i2])
        await message.answer(
            f"Пара найдена! Карточки {i1} и {i2} — это {card1}.",
            parse_mode="Markdown",
        )
    else:
        state.mistakes += 1
        await message.answer(
            f"Не совпало: {i1} — {card1}, {i2} — {card2}. Пробуй дальше!",
            parse_mode="Markdown",
        )

    if len(state.matched) == len(state.cards):
        elapsed_ms = int((time.monotonic() - state.started_at) * 1000)
        result = {
            "moves_count": state.moves_count,
            "mistakes": state.mistakes,
            "time_ms": elapsed_ms,
        }

        backend_data = None
        if state.backend_session_id is not None:
            backend_data = await _backend_finish_session(
                state.backend_session_id,
                result,
            )

        if backend_data:
            gained = backend_data["gained_xp"]
            perf = float(gained["performance_score"])
            mem_xp = int(gained["memory_xp"])
            react_xp = int(gained["reaction_xp"])
            skills = backend_data["updated_skills"]
            extra = (
                f"\n\nУровень памяти: {skills['memory_level']} "
                f"({skills['memory_xp']}/{skills['memory_xp_to_next']})"
                f"\nУровень реакции: {skills['reaction_level']} "
                f"({skills['reaction_xp']}/{skills['reaction_xp_to_next']})"
                f"\nСерия дней: {skills['daily_streak']}"
            )
        else:
            xp_gain = compute_xp_for_game(
                GameType.MEMORY_PAIRS,
                result=result,
                daily_streak=1,
                optimal_time_sec=60,
            )
            perf = xp_gain.performance_score
            mem_xp = xp_gain.memory_xp
            react_xp = xp_gain.reaction_xp
            extra = ""

        await message.answer(
            (
                "Поздравляю! Все пары найдены.\n\n"
                f"Ходы: {state.moves_count}\n"
                f"Ошибки: {state.mistakes}\n"
                f"Время: {elapsed_ms // 1000} сек\n\n"
                f"Оценка игры: {perf:.2f}\n"
                f"Память +{mem_xp}, Реакция +{react_xp}"
                f"{extra}"
            ),
            parse_mode="Markdown",
        )
        MEMORY_PAIRS_GAMES.pop(user_id, None)
    else:
        await message.answer(_render_memory_pairs_board(state), parse_mode="Markdown")


async def start_memory_sequence_game(message: Message) -> None:
    user_id = message.from_user.id
    _clear_user_games(user_id)

    state = MemorySequenceState(points=6)
    MEMORY_SEQUENCE_GAMES[user_id] = state

    # Try to start backend session (optional)
    session_id = await _backend_start_session_for_user(
        message,
        GameType.MEMORY_SEQUENCE,
    )
    state.backend_session_id = session_id

    await message.answer(
        "Игра «Маршрут комарика».\nЗапоминай последовательность точек и повторяй её.",
        parse_mode="Markdown",
    )
    await _memory_sequence_next_round(message, state)


async def _memory_sequence_next_round(message: Message, state: MemorySequenceState) -> None:
    if not state.active:
        return

    # Добавляем новый шаг в последовательность
    state.sequence.append(random.randint(1, state.points))
    state.max_sequence_length = max(state.max_sequence_length, len(state.sequence))

    seq_str = " ".join(str(x) for x in state.sequence)
    points_str = " ".join(str(i) for i in range(1, state.points + 1))

    await message.answer(
        (
            "Маршрут комарика:\n"
            f"`{seq_str}`\n\n"
            f"Точки на экране: `{points_str}`\n\n"
            "Теперь повтори последовательность, введя числа через пробел."
        ),
        parse_mode="Markdown",
    )


async def handle_memory_sequence_move(message: Message) -> None:
    user_id = message.from_user.id
    state = MEMORY_SEQUENCE_GAMES.get(user_id)
    if not state or not state.active:
        return

    text = (message.text or "").strip()
    parts = text.split()
    if not parts or not all(p.isdigit() for p in parts):
        await message.answer("Введи последовательность чисел через пробел, например: `2 5 1`.", parse_mode="Markdown")
        return

    user_seq = [int(p) for p in parts]
    correct_seq = state.sequence

    # сравнение
    length = min(len(user_seq), len(correct_seq))
    correct = sum(1 for i in range(length) if user_seq[i] == correct_seq[i])
    mistakes = len(user_seq) - correct + max(0, len(correct_seq) - len(user_seq))

    state.total_correct += correct
    state.total_mistakes += mistakes

    if user_seq == correct_seq:
        await message.answer(
            "Отлично! Последовательность верная. Усложняем маршрут...",
            parse_mode="Markdown",
        )
        # ограничим игру, например, 8 шагами
        if len(state.sequence) >= 8:
            await _finish_memory_sequence_game(message, state)
        else:
            await _memory_sequence_next_round(message, state)
    else:
        await message.answer(
            (
                "Есть ошибки в последовательности.\n"
                f"Правильная была: `{ ' '.join(str(x) for x in correct_seq) }`"
            ),
            parse_mode="Markdown",
        )
        await _finish_memory_sequence_game(message, state)


async def _finish_memory_sequence_game(message: Message, state: MemorySequenceState) -> None:
    state.active = False
    result = {
        "max_sequence_length": state.max_sequence_length,
        "total_correct": state.total_correct,
        "total_mistakes": state.total_mistakes,
    }

    backend_data = None
    if state.backend_session_id is not None:
        backend_data = await _backend_finish_session(
            state.backend_session_id,
            result,
        )

    if backend_data:
        gained = backend_data["gained_xp"]
        perf = float(gained["performance_score"])
        mem_xp = int(gained["memory_xp"])
        react_xp = int(gained["reaction_xp"])
        skills = backend_data["updated_skills"]
        extra = (
            f"\n\nУровень памяти: {skills['memory_level']} "
            f"({skills['memory_xp']}/{skills['memory_xp_to_next']})"
            f"\nУровень реакции: {skills['reaction_level']} "
            f"({skills['reaction_xp']}/{skills['reaction_xp_to_next']})"
            f"\nСерия дней: {skills['daily_streak']}"
        )
    else:
        xp_gain = compute_xp_for_game(
            GameType.MEMORY_SEQUENCE,
            result=result,
            daily_streak=1,
            target_length=8,
        )
        perf = xp_gain.performance_score
        mem_xp = xp_gain.memory_xp
        react_xp = xp_gain.reaction_xp
        extra = ""

    await message.answer(
        (
            "Игра «Маршрут комарика» завершена.\n\n"
            f"Максимальная длина маршрута: {state.max_sequence_length}\n"
            f"Правильных ответов: {state.total_correct}\n"
            f"Ошибок: {state.total_mistakes}\n\n"
            f"Оценка игры: {perf:.2f}\n"
            f"Память +{mem_xp}, Реакция +{react_xp}"
            f"{extra}"
        ),
        parse_mode="Markdown",
    )
    MEMORY_SEQUENCE_GAMES.pop(message.from_user.id, None)


async def start_reaction_hunt_game(message: Message) -> None:
    user_id = message.from_user.id
    _clear_user_games(user_id)

    state = ReactionHuntState(total_rounds=5)
    REACTION_HUNT_GAMES[user_id] = state

    # Try to start backend session (optional)
    session_id = await _backend_start_session_for_user(
        message,
        GameType.REACTION_HUNT,
    )
    state.backend_session_id = session_id

    await message.answer(
        "Игра «Охота за сигналом».\nВыбирай номер нужной цели как можно быстрее!",
        parse_mode="Markdown",
    )
    await _reaction_hunt_next_round(message, state)


async def _reaction_hunt_next_round(message: Message, state: ReactionHuntState) -> None:
    icons = ["🧠", "⚡", "🎯", "🌩", "🦟"]
    target = random.choice(icons)
    options = random.sample(icons, k=3)
    if target not in options:
        options[random.randrange(3)] = target
    random.shuffle(options)
    correct_index = options.index(target) + 1

    round_obj = ReactionRound(
        target=target,
        options=options,
        correct_index=correct_index,
        start_time=time.monotonic(),
    )
    state.current_round = round_obj

    await message.answer(
        (
            f"Раунд {state.completed_rounds + 1}/{state.total_rounds}\n"
            f"Цель: {target}\n\n"
            "Варианты:\n"
            f"1) {options[0]}\n"
            f"2) {options[1]}\n"
            f"3) {options[2]}\n\n"
            "Ответь номером 1, 2 или 3 как можно быстрее!"
        ),
        parse_mode="Markdown",
    )


async def handle_reaction_hunt_move(message: Message) -> None:
    user_id = message.from_user.id
    state = REACTION_HUNT_GAMES.get(user_id)
    if not state or not state.current_round:
        return

    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Ответь номером 1, 2 или 3.")
        return

    choice = int(text)
    if choice not in (1, 2, 3):
        await message.answer("Нужно выбрать 1, 2 или 3.")
        return

    round_obj = state.current_round
    elapsed_ms = (time.monotonic() - round_obj.start_time) * 1000.0
    state.completed_rounds += 1

    if choice == round_obj.correct_index:
        state.correct_hits += 1
        state.reaction_times_ms.append(elapsed_ms)
        await message.answer(
            f"Попадание! Время реакции: {int(elapsed_ms)} мс.",
            parse_mode="Markdown",
        )
    else:
        state.misses += 1
        await message.answer(
            f"Мимо. Цель была под номером {round_obj.correct_index}.",
            parse_mode="Markdown",
        )

    if state.completed_rounds >= state.total_rounds:
        await _finish_reaction_hunt_game(message, state)
    else:
        await _reaction_hunt_next_round(message, state)


async def _finish_reaction_hunt_game(message: Message, state: ReactionHuntState) -> None:
    if state.reaction_times_ms:
        avg_ms = sum(state.reaction_times_ms) / len(state.reaction_times_ms)
    else:
        avg_ms = 9999.0

    result = {
        "avg_reaction_ms": int(avg_ms),
        "correct_hits": state.correct_hits,
        "misses": state.misses,
    }

    backend_data = None
    if state.backend_session_id is not None:
        backend_data = await _backend_finish_session(
            state.backend_session_id,
            result,
        )

    if backend_data:
        gained = backend_data["gained_xp"]
        perf = float(gained["performance_score"])
        mem_xp = int(gained["memory_xp"])
        react_xp = int(gained["reaction_xp"])
        skills = backend_data["updated_skills"]
        extra = (
            f"\n\nУровень памяти: {skills['memory_level']} "
            f"({skills['memory_xp']}/{skills['memory_xp_to_next']})"
            f"\nУровень реакции: {skills['reaction_level']} "
            f"({skills['reaction_xp']}/{skills['reaction_xp_to_next']})"
            f"\nСерия дней: {skills['daily_streak']}"
        )
    else:
        xp_gain = compute_xp_for_game(
            GameType.REACTION_HUNT,
            result=result,
            daily_streak=1,
        )
        perf = xp_gain.performance_score
        mem_xp = xp_gain.memory_xp
        react_xp = xp_gain.reaction_xp
        extra = ""

    await message.answer(
        (
            "Игра «Охота за сигналом» завершена.\n\n"
            f"Среднее время реакции: {int(avg_ms)} мс\n"
            f"Попаданий: {state.correct_hits}\n"
            f"Промахов: {state.misses}\n\n"
            f"Оценка игры: {perf:.2f}\n"
            f"Память +{mem_xp}, Реакция +{react_xp}"
            f"{extra}"
        ),
        parse_mode="Markdown",
    )
    REACTION_HUNT_GAMES.pop(message.from_user.id, None)


async def main() -> None:
    token = os.getenv(BOT_TOKEN_ENV)
    if not token:
        raise RuntimeError(
            f"Environment variable {BOT_TOKEN_ENV} is not set. "
            "Set your Telegram bot token before running the bot."
        )

    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=token)
    dp = Dispatcher()

    dp.message.register(handle_start, CommandStart())
    dp.message.register(
        handle_game_choice,
        F.text.in_(
            [
                "🎴 Пары комариков",
                "🧠 Маршрут комарика",
                "⚡ Охота за сигналом",
            ]
        ),
    )

    # Handlers for in-chat game moves
    dp.message.register(
        handle_memory_pairs_move,
        F.text.regexp(r"^\s*\d+\s+\d+\s*$"),
    )
    dp.message.register(
        handle_memory_sequence_move,
        F.text.regexp(r"^\s*\d+(?:\s+\d+)*\s*$"),
    )
    dp.message.register(
        handle_reaction_hunt_move,
        F.text.regexp(r"^\s*[1-3]\s*$"),
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
