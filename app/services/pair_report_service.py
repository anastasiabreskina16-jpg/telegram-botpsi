from __future__ import annotations

from app.services.dialogue_test_data import FINAL_CLOSING_PHRASE, FINAL_CONVERSATION_QUESTIONS


def _format_phase2_blocks(rows: list[dict]) -> str:
    lines: list[str] = []
    for row in rows:
        lines.append(
            "• {name}: подросток {teen}, родитель {parent}, разница {diff} ({label})".format(
                name=row["block_name"],
                teen=row["teen_score"],
                parent=row["parent_score"],
                diff=row["pair_diff"],
                label=row["label"],
            )
        )
    return "\n".join(lines)


def _format_phase3_rows(rows: list[dict]) -> tuple[str, str]:
    mismatch_lines: list[str] = []
    discuss_lines: list[str] = []
    for row in rows:
        marker = "✅" if row["matched"] else "❌"
        mismatch_lines.append(f"• {marker} {row['title']}")
        if not row["matched"] and row.get("discussion_question"):
            discuss_lines.append(f"• {row['title']}: {row['discussion_question']}")
    return "\n".join(mismatch_lines), "\n".join(discuss_lines)


def build_dialogue_report(progress: dict) -> str:
    if not progress.get("completed"):
        return "Отчет пока недоступен. Ожидаем завершение всех 4 фаз обоими участниками."

    phase1 = progress["phase1"]
    phase2 = progress["phase2"]
    phase3 = progress["phase3"]
    phase4 = progress["phase4"]

    phase2_blocks = _format_phase2_blocks(phase2["blocks"])
    phase3_rows, phase3_discuss = _format_phase3_rows(phase3["rows"])
    shared_values = ", ".join(phase4["overlap_values"]) if phase4["overlap_values"] else "нет совпадений"
    final_questions = "\n".join(f"{idx}. {q}" for idx, q in enumerate(FINAL_CONVERSATION_QUESTIONS, start=1))

    return (
        "<b>Диалог о выборе - итог</b>\n\n"
        "<b>Блок 1. Фаза 1: эмоциональный фон</b>\n"
        f"• Подросток: {phase1['teen']['score']} ({phase1['teen']['word']})\n"
        f"• Родитель: {phase1['parent']['score']} ({phase1['parent']['word']})\n"
        f"• Разница эмоционального фона: {phase1['diff']}\n\n"
        "<b>Блок 2. Фаза 2: индивидуальные ответы</b>\n"
        f"• Общий балл подростка: {phase2['teen']['total']}\n"
        f"• Общий балл родителя: {phase2['parent']['total']}\n"
        + phase2_blocks
        + "\n\n"
        "<b>Блок 3. Фаза 3: совместные сценарии</b>\n"
        f"• Совпадений: {phase3['matches']}\n"
        f"• Расхождений: {phase3['mismatches']}\n"
        + (phase3_rows if phase3_rows else "• Нет данных")
        + "\n"
        + ("\nВопросы для обсуждения по расхождениям:\n" + phase3_discuss if phase3_discuss else "")
        + "\n\n"
        "<b>Блок 4. Фаза 4: ценности</b>\n"
        f"• Общие ценности: {shared_values}\n"
        f"• Количество совпадений: {phase4['overlap_count']}\n"
        f"• Интерпретация: {phase4['interpretation']}\n\n"
        "<b>Блок 5. 3 вопроса для разговора</b>\n"
        + final_questions
        + "\n\n"
        "<b>Блок 6. Финальная фраза</b>\n"
        + FINAL_CLOSING_PHRASE
    )


DISCUSSION_QUESTIONS = tuple(FINAL_CONVERSATION_QUESTIONS)

NEXT_STEPS_TEXT = (
    "Следующий шаг:\n\n"
    "• Зафиксировать 1 совместный шаг на 2 недели\n"
    "• Вернуться к блоку с самым большим расхождением\n"
    "• Провести короткий повторный диалог через неделю"
)
