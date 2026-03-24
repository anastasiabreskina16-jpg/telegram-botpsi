"""Smoke tests for gamification progress system."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.progress_service import (
    ACHIEVEMENTS,
    MISSIONS,
    POINTS_PER_LEVEL_UP,
    calculate_level,
    check_achievements,
    format_level_up_message,
    format_progress_display,
    format_streak_milestone,
    get_next_mission,
    update_streak,
)


class FakeUser:
    """Mock user for testing."""

    def __init__(
        self,
        points: int = 0,
        level: int = 1,
        streak_days: int = 0,
        last_activity: datetime | None = None,
    ):
        self.points = points
        self.level = level
        self.streak_days = streak_days
        self.last_activity = last_activity


def test_calculate_level_basic():
    """Test level calculation from points."""
    assert calculate_level(0) == 1
    assert calculate_level(50) == 1
    assert calculate_level(99) == 1
    assert calculate_level(100) == 2
    assert calculate_level(200) == 3
    assert calculate_level(500) == 6


def test_calculate_level_progression():
    """Test that levels increment properly."""
    for points in range(0, 1000, 100):
        expected_level = (points // POINTS_PER_LEVEL_UP) + 1
        assert calculate_level(points) == expected_level


def test_update_streak_first_activity():
    """Test streak initialization."""
    user = FakeUser()
    new_streak = update_streak(user)

    assert new_streak == 1
    assert user.streak_days == 1
    assert user.last_activity is not None


def test_update_streak_same_day():
    """Test same-day streak doesn't increment."""
    now = datetime.now(timezone.utc)
    user = FakeUser(streak_days=3, last_activity=now)

    new_streak = update_streak(user)

    assert new_streak == 3  # No increment
    assert user.streak_days == 3


def test_update_streak_next_day():
    """Test next-day streak increments."""
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    user = FakeUser(streak_days=3, last_activity=yesterday)

    new_streak = update_streak(user)

    assert new_streak == 4  # Incremented
    assert user.streak_days == 4


def test_update_streak_gap_resets():
    """Test streak resets after gap > 1 day."""
    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
    user = FakeUser(streak_days=5, last_activity=two_days_ago)

    new_streak = update_streak(user)

    assert new_streak == 1  # Reset
    assert user.streak_days == 1


def test_get_next_mission():
    """Test mission selection by level."""
    user1 = FakeUser(level=1)
    user2 = FakeUser(level=2)
    user3 = FakeUser(level=6)  # Cycles back

    mission1 = get_next_mission(user1)
    mission2 = get_next_mission(user2)
    mission3 = get_next_mission(user3)

    assert mission1 == MISSIONS[0]
    assert mission2 == MISSIONS[1]
    assert mission3 == MISSIONS[0]  # Cycles


def test_format_progress_display():
    """Test progress display formatting."""
    user = FakeUser(points=150, level=2, streak_days=7)

    display = format_progress_display(user)

    assert "🏆" in display
    assert "Уровень:" in display and "2" in display
    assert "Очки:" in display and "150" in display
    assert "Серия:" in display and "7" in display
    assert "Следующая миссия:" in display


def test_format_level_up_message():
    """Test level-up notification."""
    msg = format_level_up_message(5)

    assert "🔥" in msg
    assert "уровень 5" in msg
    assert "Новая миссия:" in msg


def test_format_streak_milestone_7_days():
    """Test 7-day streak milestone."""
    msg = format_streak_milestone(7)

    assert "🔥" in msg
    assert "Серия 7 дней" in msg
    assert "на огне" in msg


def test_format_streak_milestone_3_days():
    """Test 3-day streak milestone (sub-milestone)."""
    msg = format_streak_milestone(3)

    assert "🔥" in msg
    assert "Серия 3 дней" in msg


def test_format_streak_no_milestone():
    """Test non-milestone streak returns empty."""
    msg = format_streak_milestone(2)

    assert msg == ""


def test_check_achievements_first_test():
    """Test first test achievement."""
    user = FakeUser()

    unlocked = check_achievements(user, tests_completed=1)

    assert "first_test" in unlocked
    assert "🎯 Первый тест" in [ACHIEVEMENTS[k] for k in unlocked]


def test_check_achievements_streak_7_days():
    """Test 7-day streak achievement."""
    user = FakeUser(streak_days=7)

    unlocked = check_achievements(user)

    assert "streak_7" in unlocked
    assert "streak_3" in unlocked  # Also unlocks 3-day


def test_check_achievements_level_5():
    """Test level 5 achievement."""
    user = FakeUser(level=5)

    unlocked = check_achievements(user)

    assert "level_5" in unlocked


def test_missions_list_is_non_empty():
    """Test that missions list has content."""
    assert len(MISSIONS) > 0
    assert all(isinstance(m, str) for m in MISSIONS)
    assert all(len(m) > 0 for m in MISSIONS)


def test_achievements_has_expected_keys():
    """Test achievements dictionary is complete."""
    expected_keys = {
        "first_test",
        "three_tests",
        "ten_tests",
        "streak_3",
        "streak_7",
        "streak_30",
        "five_missions",
        "level_5",
        "level_10",
    }
    assert set(ACHIEVEMENTS.keys()) == expected_keys
