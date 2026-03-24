from app.services.retention_service import process_retention_reminders, touch_user_activity


def test_retention_smoke_imports() -> None:
    assert process_retention_reminders is not None
    assert touch_user_activity is not None
