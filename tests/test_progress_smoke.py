from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.result_service import build_progress_text, compare_results


def test_compare_results() -> None:
    current = {"confidence": 5}
    previous = {"confidence": 3}

    delta = compare_results(current, previous)

    assert delta is not None
    assert delta["confidence"] == 2


def test_build_progress_text_first_result() -> None:
    text = build_progress_text(None)
    assert "первый результат" in text


def test_build_progress_text_uses_human_labels() -> None:
    text = build_progress_text({"independence": 2, "anxiety": -1, "control": 0})
    assert "самостоятельность" in text
    assert "тревога и барьеры" in text
    assert "локус контроля" in text
