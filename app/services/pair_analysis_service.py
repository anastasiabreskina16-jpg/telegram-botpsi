from __future__ import annotations

import asyncio
import logging

from app.services.pair_test_service import get_pair_session_by_id_for_update, get_phase2_answers_for_role
from app.services.result_service import get_last_result, save_result

log = logging.getLogger(__name__)


def _reset_sent_reports_for_testing() -> None:
    """Test helper kept for backward compatibility."""
    return None

BLOCKS: dict[str, list[int]] = {
    "independence": [0, 1],
    "anxiety": [2, 3],
    "control": [4, 5],
    "perfectionism": [6, 7],
    "pressure": [8, 9],
    "identity": [10, 11],
}

REVERSE_BLOCKS = {"anxiety", "perfectionism", "pressure"}

BLOCK_LABELS = {
    "independence": "самостоятельность",
    "anxiety": "тревога и барьеры",
    "control": "локус контроля",
    "perfectionism": "перфекционизм",
    "pressure": "социальное давление",
    "identity": "идентичность",
}

FINAL_QUESTIONS = [
    "Что вас удивило?",
    "Где самое большое расхождение?",
    "Что вам нужно друг от друга сейчас?",
]


def get_top_conflict(diff: dict[str, dict[str, int | str]]) -> str | None:
    """Find the block with the largest difference.
    
    Args:
        diff: Dictionary mapping block names to their metrics
        
    Returns:
        Block name with max difference, or None if diff is empty
    """
    if not diff:
        return None
    
    # Find max difference by absolute value of diff key
    max_block = max(
        diff.items(),
        key=lambda x: abs(int(x[1].get("diff", 0)))
    )
    return max_block[0]


def build_mission_block(diff: dict[str, dict[str, int | str]]) -> str:
    """Build a personalized mission block based on top conflict.
    
    Args:
        diff: Dictionary with block metrics
        
    Returns:
        Formatted mission text with static template
    """
    top_block = get_top_conflict(diff)
    if not top_block:
        return "\n\n🎯 Задание на 2 дня:\n\nОбсудите один пункт, где вы не совпали.\nВажно: без критики — только попытка понять друг друга."
    
    label = BLOCK_LABELS.get(top_block, top_block)
    return f"""\n\n🎯 Задание на 2 дня:

Обсудите тему: «{label}»

Попробуйте понять позицию друг друга без спора.

Срок: 2-3 дня. Затем пройдите тест снова, чтобы увидеть, что изменилось."""


def _ordered_answers(
    answer_map: dict[int, int], total: int = 12
) -> list[int]:
    return [int(answer_map.get(idx, 0)) for idx in range(1, total + 1)]


def calculate_blocks(
    answers: list[int],
) -> dict[str, int]:
    if len(answers) < 12:
        raise ValueError("insufficient_answers")

    results: dict[str, int] = {}
    for block, idxs in BLOCKS.items():
        raw = sum(answers[i] for i in idxs)
        score = 10 - raw if block in REVERSE_BLOCKS else raw
        results[block] = int(score)
    return results


def compare(
    teen: dict[str, int],
    parent: dict[str, int],
) -> dict[str, dict[str, int | str]]:
    diff: dict[str, dict[str, int | str]] = {}

    for block in teen:
        d = abs(teen[block] - parent[block])
        if d <= 1:
            status = "match"
        elif d <= 3:
            status = "gap"
        else:
            status = "conflict"

        diff[block] = {
            "teen": teen[block],
            "parent": parent[block],
            "diff": d,
            "status": status,
        }

    return diff


def _block_line(
    block: str,
    data: dict[str, int | str],
) -> str:
    label = BLOCK_LABELS.get(block, block)
    teen_score = int(data["teen"])
    parent_score = int(data["parent"])
    status = data["status"]

    if status == "conflict":
        marker = "❗"
        head = f"Сильное расхождение в блоке «{label}»."
    elif status == "gap":
        marker = "⚠️"
        head = f"Есть различие во взглядах в блоке «{label}»."
    else:
        marker = "✅"
        head = f"В блоке «{label}» вы хорошо понимаете друг друга."

    if teen_score > parent_score:
        tail = "Подросток оценивает это выше, чем это видит родитель."
    elif teen_score < parent_score:
        tail = "Родитель видит это выше, чем это ощущает подросток."
    else:
        tail = "Оценки совпадают."

    return f"{marker} {head}\nПодросток: {teen_score}, родитель: {parent_score}. {tail}"


def build_report(
    diff: dict[str, dict[str, int | str]],
) -> str:
    lines = ["<b>Сравнение взглядов: подросток и родитель</b>"]

    # Summary header — top conflict and top match
    conflicts = sorted(
        [(b, d) for b, d in diff.items() if d["status"] == "conflict"],
        key=lambda x: int(x[1]["diff"]),
        reverse=True,
    )
    matches = [b for b, d in diff.items() if d["status"] == "match"]

    summary: list[str] = []
    if conflicts:
        top_label = BLOCK_LABELS.get(conflicts[0][0], conflicts[0][0])
        summary.append(f"❗ Самое сильное расхождение: «{top_label}»")
    if matches:
        top_match_label = BLOCK_LABELS.get(matches[0], matches[0])
        summary.append(f"✅ Вы хорошо понимаете друг друга в: «{top_match_label}»")
    if not conflicts and not matches:
        summary.append("⚠️ Есть несколько зон для обсуждения.")
    summary.append("Давайте обсудим детали и различия 👇")
    lines.append("\n".join(summary))

    for block in BLOCKS:
        data = diff.get(block)
        if data is None:
            continue
        lines.append(_block_line(block, data))

    lines.append("\n<b>3 вопроса для разговора</b>")
    for idx, question in enumerate(FINAL_QUESTIONS, start=1):
        lines.append(f"{idx}. {question}")

    return "\n\n".join(lines)


async def build_phase2_comparison_report(
    session, *, pair_session_id: int
) -> str | None:
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as fresh_session:
        pair_session = await get_pair_session_by_id_for_update(fresh_session, pair_session_id=pair_session_id)
        if pair_session is None:
            return None
        if pair_session.phase2_report_sent:
            return None

        teen_map = await get_phase2_answers_for_role(fresh_session, pair_session_id=pair_session_id, role="teen")
        parent_map = await get_phase2_answers_for_role(fresh_session, pair_session_id=pair_session_id, role="parent")

        teen_scores = calculate_blocks(_ordered_answers(teen_map))
        parent_scores = calculate_blocks(_ordered_answers(parent_map))
        diff = compare(teen_scores, parent_scores)

        previous_diff = None
        if pair_session.teen_user_id is not None:
            teen_last_result = await get_last_result(fresh_session, pair_session.teen_user_id)
            if teen_last_result is not None:
                previous_diff = teen_last_result.diff
        if previous_diff is None and pair_session.parent_user_id is not None:
            parent_last_result = await get_last_result(fresh_session, pair_session.parent_user_id)
            if parent_last_result is not None:
                previous_diff = parent_last_result.diff

        structured = build_report(diff)

        from app.services.ai_report_service import get_or_create_ai_report
        try:
            ai_text = await asyncio.wait_for(
                get_or_create_ai_report(
                    fresh_session,
                    pair_session_id=pair_session_id,
                    diff=diff,
                    previous_diff=previous_diff,
                    teen_scores=teen_scores,
                    parent_scores=parent_scores,
                ),
                timeout=5,
            )
        except asyncio.TimeoutError:
            ai_text = None
        except Exception:
            ai_text = None

        if ai_text:
            final_text = structured + "\n\n🧠 <b>Как это выглядит со стороны:</b>\n\n" + ai_text
        else:
            final_text = structured

        # Add personalized mission
        mission_text = build_mission_block(diff)
        final_text += mission_text

        for uid in [pair_session.teen_user_id, pair_session.parent_user_id]:
            if uid is None:
                continue
            await save_result(
                session=fresh_session,
                user_id=uid,
                pair_session_id=pair_session.id,
                teen_scores=teen_scores,
                parent_scores=parent_scores,
                diff=diff,
                ai_report=final_text,
            )

        pair_session.phase2_report_sent = True
        await fresh_session.commit()
        log.info("AI_REPORT pair=%s generated=%s", pair_session_id, bool(ai_text))

        return final_text
