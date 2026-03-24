"""Gamification progress service: points, levels, streaks, missions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


# ── Constants ──────────────────────────────────────────────────────────────────

POINTS_PER_TEST = 50
POINTS_PER_MISSION = 20
POINTS_PER_RETURN = 10
POINTS_PER_LEVEL_UP = 100

MISSIONS = [
    "Обсудить 1 расхождение",
    "Задать 3 вопроса друг другу",
    "Понять точку зрения без спора",
    "Провести семейный совет",
    "Определить общую цель",
]

ACHIEVEMENTS = {
    "first_test": "🎯 Первый тест",
    "three_tests": "🏆 Три теста",
    "ten_tests": "👑 Десять тестов",
    "streak_3": "🔥 Серия 3 дня",
    "streak_7": "❤️ Серия 7 дней",
    "streak_30": "💎 Серия 30 дней",
    "five_missions": "🎪 Пять миссий",
    "level_5": "⭐ Уровень 5",
    "level_10": "✨ Уровень 10",
}


# ── Level Calculation ──────────────────────────────────────────────────────────

def calculate_level(points: int) -> int:
    """Calculate user level based on points.
    
    Formula: level = (points // 100) + 1
    - Level 1: 0-99 points
    - Level 2: 100-199 points
    - Level 3: 200-299 points
    etc.
    """
    return max(1, (points // POINTS_PER_LEVEL_UP) + 1)


# ── Streak Management ──────────────────────────────────────────────────────────

def update_streak(user: User) -> int:
    """Update user streak based on activity.
    
    Returns new streak count.
    """
    now = datetime.now(timezone.utc)

    if user.last_activity is None:
        user.streak_days = 1
        user.last_activity = now
        return 1

    last_date = user.last_activity.date()
    today = now.date()

    # Same day: no change
    if today == last_date:
        return user.streak_days

    # Next day: increment streak
    if today == last_date + timedelta(days=1):
        user.streak_days += 1
    else:
        # Gap > 1 day: reset streak
        user.streak_days = 1

    user.last_activity = now
    return user.streak_days


# ── Points Management ──────────────────────────────────────────────────────────

async def add_points(
    user: User,
    points: int,
    *,
    session: AsyncSession | None = None,
) -> tuple[int, int, int]:
    """Add points to user and update level.
    
    Args:
        user: User object to update
        points: Points to add
        session: Optional AsyncSession for commit
        
    Returns:
        Tuple of (new_points, new_level, old_level)
    """
    old_level = user.level
    user.points += points
    user.level = calculate_level(user.points)
    
    if session:
        await session.commit()

    return user.points, user.level, old_level


async def award_test_completion(user: User, *, session: AsyncSession | None = None) -> dict:
    """Award points for completing a test.
    
    Returns:
        Dict with keys: points, level, is_level_up, streak
    """
    new_points, new_level, old_level = await add_points(
        user,
        POINTS_PER_TEST,
        session=session,
    )
    new_streak = update_streak(user)

    if session:
        await session.commit()

    return {
        "points": new_points,
        "level": new_level,
        "is_level_up": new_level > old_level,
        "streak": new_streak,
    }


async def award_mission_completion(user: User, *, session: AsyncSession | None = None) -> dict:
    """Award points for completing a mission.
    
    Returns:
        Dict with keys: points, level, is_level_up
    """
    new_points, new_level, old_level = await add_points(
        user,
        POINTS_PER_MISSION,
        session=session,
    )

    if session:
        await session.commit()

    return {
        "points": new_points,
        "level": new_level,
        "is_level_up": new_level > old_level,
    }


async def award_return_activity(user: User, *, session: AsyncSession | None = None) -> dict:
    """Award points for returning to the app.
    
    Returns:
        Dict with keys: points, level, is_level_up, streak
    """
    new_points, new_level, old_level = await add_points(
        user,
        POINTS_PER_RETURN,
        session=session,
    )
    new_streak = update_streak(user)

    if session:
        await session.commit()

    return {
        "points": new_points,
        "level": new_level,
        "is_level_up": new_level > old_level,
        "streak": new_streak,
    }


# ── Mission Management ─────────────────────────────────────────────────────────

def get_next_mission(user: User) -> str:
    """Get next mission for user based on level.
    
    Missions cycle through based on level.
    """
    mission_idx = (user.level - 1) % len(MISSIONS)
    return MISSIONS[mission_idx]


# ── Achievement Checking ──────────────────────────────────────────────────────

def check_achievements(
    user: User,
    *,
    tests_completed: int = 0,
    missions_completed: int = 0,
) -> list[str]:
    """Check which achievements user has unlocked.
    
    Args:
        user: User object
        tests_completed: Total tests completed (passed as context)
        missions_completed: Total missions completed (passed as context)
        
    Returns:
        List of achievement keys unlocked in this check
    """
    unlocked = []

    # Test achievements
    if tests_completed == 1:
        unlocked.append("first_test")
    elif tests_completed == 3:
        unlocked.append("three_tests")
    elif tests_completed == 10:
        unlocked.append("ten_tests")

    # Streak achievements
    if user.streak_days >= 3:
        unlocked.append("streak_3")
    if user.streak_days >= 7:
        unlocked.append("streak_7")
    if user.streak_days >= 30:
        unlocked.append("streak_30")

    # Mission achievements
    if missions_completed == 5:
        unlocked.append("five_missions")

    # Level achievements
    if user.level >= 5:
        unlocked.append("level_5")
    if user.level >= 10:
        unlocked.append("level_10")

    return unlocked


# ── Progress Display ──────────────────────────────────────────────────────────

def format_progress_display(user: User) -> str:
    """Format user progress for display.
    
    Returns:
        Formatted progress text with emojis.
    """
    next_level_points = calculate_level(user.points + 1) * POINTS_PER_LEVEL_UP
    progress_to_next = next_level_points - user.points
    
    return f"""🏆 <b>Твой прогресс</b>

📊 Уровень: <b>{user.level}</b>
⭐ Очки: <b>{user.points}</b> (до уровня {user.level + 1}: <b>+{progress_to_next}</b>)
🔥 Серия: <b>{user.streak_days}</b> дней

🎯 Следующая миссия: {get_next_mission(user)}"""


def format_level_up_message(new_level: int) -> str:
    """Format level-up notification.
    
    Returns:
        Formatted notification text.
    """
    return f"""🔥 <b>Ты вышел на уровень {new_level}!</b>

Поздравляем! Ты растёшь 💪

🎯 Новая миссия: {MISSIONS[(new_level - 1) % len(MISSIONS)]}"""


def format_streak_milestone(streak: int) -> str:
    """Format streak milestone notification.
    
    Returns:
        Formatted notification text, or empty string if not a milestone.
    """
    if streak % 7 == 0:
        return f"""🔥 <b>Серия {streak} дней!</b>

Ты на огне 🌟 Продолжай в том же духе!"""
    elif streak % 3 == 0 and streak < 30:
        return f"""🔥 <b>Серия {streak} дней!</b>

Нужно ещё совсем немного!"""
    return ""
