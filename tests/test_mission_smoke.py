"""Smoke tests for AI Coach missions feature."""
from __future__ import annotations

from app.services.pair_analysis_service import (
    BLOCK_LABELS,
    build_mission_block,
    get_top_conflict,
)


def test_get_top_conflict():
    """Test finding the largest conflict point."""
    diff = {
        "independence": {"teen": 5, "parent": 3, "diff": 2, "status": "gap"},
        "anxiety": {"teen": 8, "parent": 2, "diff": 6, "status": "conflict"},
        "control": {"teen": 4, "parent": 4, "diff": 0, "status": "match"},
    }

    result = get_top_conflict(diff)

    # anxiety has the largest diff (6)
    assert result == "anxiety"


def test_get_top_conflict_handles_empty():
    """Test get_top_conflict with empty diff."""
    diff = {}

    result = get_top_conflict(diff)

    assert result is None


def test_build_mission_block_with_conflict():
    """Test mission block generation with real conflict."""
    diff = {
        "independence": {"teen": 5, "parent": 3, "diff": 2, "status": "gap"},
        "anxiety": {"teen": 8, "parent": 2, "diff": 6, "status": "conflict"},
    }

    mission = build_mission_block(diff)

    # Should contain:
    # - 🎯 emoji for mission
    # - Russian label for "anxiety"
    # - Instruction to discuss
    # - Time frame
    assert "🎯" in mission
    assert "тревога и барьеры" in mission
    assert "Обсудите" in mission
    assert "2-3 дня" in mission


def test_build_mission_block_shows_correct_label():
    """Test that mission uses human-readable labels."""
    diff = {
        "perfectionism": {"teen": 6, "parent": 4, "diff": 2, "status": "gap"},
    }

    mission = build_mission_block(diff)

    # Should use the label from BLOCK_LABELS
    assert "перфекционизм" in mission


def test_build_mission_block_empty_diff():
    """Test mission block with empty diff."""
    diff = {}

    mission = build_mission_block(diff)

    # Should still return a mission text (generic one)
    assert "🎯" in mission
    assert "Задание" in mission
    assert "2 дня" in mission or "2-3 дня" in mission


def test_mission_block_format():
    """Test that mission block has proper formatting."""
    diff = {
        "identity": {"teen": 7, "parent": 5, "diff": 2, "status": "gap"},
    }

    mission = build_mission_block(diff)

    # Should be a multi-line formatted string
    assert len(mission) > 50  # Not too short
    assert "\n" in mission  # Has line breaks
    assert "Обсудите" in mission  # Has action word
    assert "друг друга" in mission  # Emphasizes mutual understanding
