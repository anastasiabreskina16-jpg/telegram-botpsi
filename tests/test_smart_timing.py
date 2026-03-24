from datetime import datetime, timedelta, timezone

from app.db.models import UserBehavior
from app.services.retention_service import get_best_send_time, should_send_now, update_active_hours, update_response_time


def test_update_active_hours_collects_hour_counts() -> None:
    behavior = UserBehavior(user_id=1, active_hours_json={})
    timestamp = datetime(2026, 3, 23, 18, 0, tzinfo=timezone.utc)

    update_active_hours(behavior, timestamp)
    update_active_hours(behavior, timestamp)

    assert behavior.active_hours_json == {"18": 2}


def test_get_best_send_time_prefers_recently_active_user() -> None:
    now = datetime(2026, 3, 23, 18, 0, tzinfo=timezone.utc)
    behavior = UserBehavior(
        user_id=1,
        last_seen_at=now - timedelta(minutes=3),
        avg_response_time=900,
        active_hours_json={"18": 4, "19": 2},
        notification_count_today=0,
    )

    run_at = get_best_send_time(behavior, now=now)

    assert run_at == now + timedelta(minutes=5)


def test_should_send_now_respects_recent_notification_gap() -> None:
    now = datetime(2026, 3, 23, 18, 0, tzinfo=timezone.utc)
    behavior = UserBehavior(
        user_id=1,
        last_seen_at=now - timedelta(minutes=2),
        last_notification_at=now - timedelta(minutes=30),
        notification_count_today=1,
        notification_day=now,
        active_hours_json={"18": 3},
    )

    assert should_send_now(behavior, now=now) is False


def test_update_response_time_uses_weighted_average() -> None:
    behavior = UserBehavior(user_id=1, avg_response_time=100)

    update_response_time(behavior, 200)

    assert behavior.avg_response_time == 130