from __future__ import annotations

import builtins

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Answer, TestSession
from app.services.test_service import TEST_BLOCKS, TEEN_TEST_QUESTIONS

sorted = builtins.sorted
len = builtins.len
round = builtins.round

TYPE_LABELS = {
    "A": "Лидер-Достигатор",
    "B": "Аналитик-Наблюдатель",
    "C": "Коммуникатор-Творец",
    "D": "Стратег-Организатор",
}

TYPE_BRIEF = {
    "A": "инициативность, энергия и ориентация на результат",
    "B": "аналитичность, точность и глубина понимания",
    "C": "эмпатия, креатив и сильная коммуникация",
    "D": "системность, планирование и стратегическое мышление",
}

TYPE_STRENGTHS = {
    "A": "Берёт ответственность, быстро включает команду и доводит до заметного результата.",
    "B": "Хорошо видит закономерности, замечает детали и повышает качество решений.",
    "C": "Создаёт контакт, помогает людям договориться и генерирует живые идеи.",
    "D": "Строит устойчивые процессы, удерживает долгие цели и снижает хаос.",
}

TYPE_CHALLENGES = {
    "A": "Может торопиться и недооценивать подготовительный этап.",
    "B": "Может застревать в анализе и дольше переходить к действию.",
    "C": "Может сильнее зависеть от эмоционального фона и внешней оценки.",
    "D": "Может быть слишком жёстким к изменениям и непредсказуемости.",
}

TYPE_DIRECTIONS = {
    "A": "направления с динамикой, ответственностью и управленческими задачами",
    "B": "направления с исследованием, аналитикой и экспертной глубиной",
    "C": "направления с людьми, коммуникацией, креативом и совместными проектами",
    "D": "направления с системной работой, архитектурой процессов и долгим циклом",
}

QUESTION_BLOCK_BY_CODE = {
    question["code"]: question["block"] for question in TEEN_TEST_QUESTIONS
}



def _normalize_text(value):
    if value is None:
        return ""
    return f"{value}".strip()



def _count_items(items):
    total = 0
    for _ in items:
        total += 1
    return total



def _collapse_spaces(text):
    parts = text.split()
    return " ".join(parts)



def _char_stats(text):
    counts = {}
    total = 0
    for ch in text:
        total += 1
        counts[ch] = counts.get(ch, 0) + 1
    return counts, total



def _is_noise_like(text):
    raw = _normalize_text(text)
    compact = raw.replace(" ", "")
    if not compact:
        return True

    noise_chars = ".,!?:;-_()[]{}'\"~*+="
    only_noise = True
    for ch in compact:
        if ch not in noise_chars:
            only_noise = False
            break
    if only_noise:
        return True

    lowered = compact.lower()
    counts, total = _char_stats(lowered)
    if total == 0:
        return True

    max_count = 0
    for value in counts.values():
        if value > max_count:
            max_count = value

    unique_count = _count_items(counts)
    if unique_count == 1:
        return True

    if max_count * 100 >= total * 80:
        return True

    return False



def normalize_answer_value(raw):
    cleaned = _collapse_spaces(_normalize_text(raw))
    if not cleaned:
        return None

    compact = cleaned.replace(" ", "")
    if _count_items(compact) < 3:
        return None

    if _is_noise_like(cleaned):
        return None

    return cleaned



def _extract_answer_map(answers):
    answer_map = {}
    for answer in answers:
        answer_map[answer.question_code] = _normalize_text(answer.answer_value).upper()[:1]
    return answer_map



def _init_letter_counts():
    return {"A": 0, "B": 0, "C": 0, "D": 0}



def _sorted_type_codes(type_scores):
    return sorted(type_scores.keys(), key=lambda code: (-type_scores[code], code))



def _calculate_metrics(answers):
    answer_map = _extract_answer_map(answers)
    type_scores = _init_letter_counts()
    block_scores = {block: _init_letter_counts() for block in TEST_BLOCKS}

    answered_count = 0
    for code, value in answer_map.items():
        if value not in type_scores:
            continue
        answered_count += 1
        type_scores[value] += 1

        block = QUESTION_BLOCK_BY_CODE.get(code)
        if block is None:
            continue
        block_scores[block][value] += 1

    sorted_codes = _sorted_type_codes(type_scores)
    dominant = sorted_codes[0]
    secondary = sorted_codes[1]
    mixed_profile = (type_scores[dominant] - type_scores[secondary]) <= 2

    block_leading_types = {}
    for block in TEST_BLOCKS:
        block_types = block_scores[block]
        ranked = _sorted_type_codes(block_types)
        block_leading_types[block] = ranked[0]

    return {
        "answered_count": answered_count,
        "total_questions": len(TEEN_TEST_QUESTIONS),
        "type_scores": type_scores,
        "dominant_type": dominant,
        "secondary_type": secondary,
        "mixed_profile": mixed_profile,
        "block_scores": block_scores,
        "block_leading_types": block_leading_types,
    }



def _format_type_line(type_code):
    return f"{type_code} - {TYPE_LABELS[type_code]}"



def _build_teen_text(metrics):
    dominant = metrics["dominant_type"]
    secondary = metrics["secondary_type"]
    mixed_profile = metrics["mixed_profile"]

    mixed_line = ""
    if mixed_profile:
        mixed_line = (
            "Профиль смешанный: разница между ведущим и дополнительным типами не превышает 2 балла.\n"
        )

    return (
        "Тест завершён. Ваш профиль по модели из 30 вопросов:\n\n"
        f"Ведущий тип: {_format_type_line(dominant)}\n"
        f"Дополнительный тип: {_format_type_line(secondary)}\n"
        f"Счёт по типам (из {metrics['total_questions']}): "
        f"A={metrics['type_scores']['A']}, B={metrics['type_scores']['B']}, "
        f"C={metrics['type_scores']['C']}, D={metrics['type_scores']['D']}\n"
        f"{mixed_line}\n"
        f"Краткое описание:\n"
        f"{TYPE_LABELS[dominant]} - это про {TYPE_BRIEF[dominant]}.\n\n"
        f"Что у вас получается:\n"
        f"{TYPE_STRENGTHS[dominant]}\n\n"
        f"Где может быть сложно:\n"
        f"{TYPE_CHALLENGES[dominant]}\n\n"
        "Что важно учитывать в выборе направления:\n"
        f"Лучше рассматривать {TYPE_DIRECTIONS[dominant]}. "
        f"Дополнительный ресурс даёт {TYPE_LABELS[secondary].lower()}."
    )



def _build_block_comparison(parent_metrics, teen_metrics):
    matches = []
    mismatches = []

    for block in TEST_BLOCKS:
        parent_type = parent_metrics["block_leading_types"][block]
        teen_type = teen_metrics["block_leading_types"][block]
        if parent_type == teen_type:
            matches.append(f"{block}: {parent_type}")
        else:
            mismatches.append(f"{block}: parent={parent_type}, teen={teen_type}")

    match_percent = round((len(matches) / len(TEST_BLOCKS)) * 100)
    return {
        "match_percent": match_percent,
        "matches": matches,
        "mismatches": mismatches,
    }



def _join_or_fallback(items, fallback):
    if not items:
        return fallback
    return "\n".join(f"- {item}" for item in items)



def _build_parent_text(parent_metrics, teen_metrics):
    parent_type = parent_metrics["dominant_type"]
    teen_type = teen_metrics["dominant_type"]
    comparison = _build_block_comparison(parent_metrics, teen_metrics)

    return (
        "Родительский тест завершён. Ниже итог по структуре из 30 вопросов и 8 блоков.\n\n"
        "1) Ваш взгляд на ребёнка\n"
        f"Ведущий тип: {_format_type_line(parent_type)}. "
        f"Дополнительный тип: {_format_type_line(parent_metrics['secondary_type'])}.\n\n"
        "2) Степень совпадения с ребёнком\n"
        f"Ведущий тип подростка: {_format_type_line(teen_type)}. "
        f"Совпадение по 8 блокам: {comparison['match_percent']}%.\n\n"
        "3) Точки взаимопонимания\n"
        f"{_join_or_fallback(comparison['matches'], 'Пока нет ярко выраженных совпадений, нужен дополнительный диалог.') }\n\n"
        "4) Зоны расхождения и напряжения\n"
        f"{_join_or_fallback(comparison['mismatches'], 'Явных зон конфликта не выявлено.') }\n\n"
        "5) Сильные стороны ребёнка\n"
        f"{TYPE_STRENGTHS[teen_type]}\n\n"
        "6) Подходящие профессии / направления\n"
        f"Рекомендуется смотреть в сторону: {TYPE_DIRECTIONS[teen_type]}.\n\n"
        "7) План шагов на 3 месяца\n"
        "- 1-й месяц: наблюдайте 2-3 учебные/внеучебные активности по блоку интересов и мотивации.\n"
        "- 2-й месяц: обсудите с ребёнком расхождения по блокам и зафиксируйте, что совпало.\n"
        "- 3-й месяц: выберите один пробный проект/курс и оцените динамику по стрессу и обучению."
    )



def _build_parent_text_without_teen(parent_metrics):
    parent_type = parent_metrics["dominant_type"]
    return (
        "Родительский тест завершён.\n\n"
        "Ваш взгляд на ребёнка:\n"
        f"Ведущий тип: {_format_type_line(parent_type)}. "
        f"Дополнительный тип: {_format_type_line(parent_metrics['secondary_type'])}.\n\n"
        "Для честного сравнения с самоощущением подростка пока не хватает подросткового теста. "
        "После прохождения teen-версии станет доступно сравнение по 8 блокам и зонам расхождения."
    )



def _build_ai_context(role, metrics, teen_metrics):
    context = {
        "role": role,
        "teen_type": None,
        "parent_type": None,
        "teen_scores": None,
        "parent_scores": None,
        "block_match_percent": None,
        "block_matches": [],
        "block_mismatches": [],
    }

    if role == "teen":
        context["teen_type"] = metrics["dominant_type"]
        context["teen_scores"] = metrics["type_scores"]
        return context

    context["parent_type"] = metrics["dominant_type"]
    context["parent_scores"] = metrics["type_scores"]

    if teen_metrics is None:
        return context

    comparison = _build_block_comparison(metrics, teen_metrics)
    context["teen_type"] = teen_metrics["dominant_type"]
    context["teen_scores"] = teen_metrics["type_scores"]
    context["block_match_percent"] = comparison["match_percent"]
    context["block_matches"] = comparison["matches"]
    context["block_mismatches"] = comparison["mismatches"]
    return context


async def get_answers_for_session(session: AsyncSession, *, session_id):
    result = await session.execute(
        select(Answer)
        .where(Answer.session_id == session_id)
        .order_by(Answer.id.asc())
    )
    return result.scalars().all()


async def get_last_completed_session(session: AsyncSession, *, user_id):
    result = await session.execute(
        select(TestSession)
        .where(
            TestSession.user_id == user_id,
            TestSession.status == "completed",
        )
        .order_by(desc(TestSession.id))
    )
    return result.scalars().first()



def build_report_stub(answers, role, teen_answers=None):
    if not answers:
        return {"has_answers": False}

    metrics = _calculate_metrics(answers)
    teen_metrics = _calculate_metrics(teen_answers) if teen_answers else None

    if role == "parent":
        if teen_metrics is None:
            text = _build_parent_text_without_teen(metrics)
        else:
            text = _build_parent_text(metrics, teen_metrics)
    else:
        text = _build_teen_text(metrics)

    return {
        "has_answers": True,
        "text": text,
        "summary_intro": "Спасибо! Тест завершён.",
        "metrics": metrics,
        "teen_metrics": teen_metrics,
        "ai_context": _build_ai_context(role, metrics, teen_metrics),
    }


def build_teen_report(answers):
    """Build personal report for teen role (answers about self)."""
    return build_report_stub(answers, "teen")


def build_parent_report(answers, teen_answers=None):
    """Build personal report for parent role (answers about child), with optional teen comparison."""
    return build_report_stub(answers, "parent", teen_answers=teen_answers)



def render_report_text(report_stub):
    if not report_stub.get("has_answers"):
        return "Тест завершен, но итог пока недоступен. Попробуйте /restart."

    ready_text = _normalize_text(report_stub.get("text"))
    if ready_text:
        return ready_text

    summary_intro = _normalize_text(report_stub.get("summary_intro"))
    if not summary_intro:
        summary_intro = "Спасибо! Тест завершён ✅"

    dominant_focus = _normalize_text(report_stub.get("dominant_focus"))
    strength_hint = _normalize_text(report_stub.get("strength_hint"))
    work_style_hint = _normalize_text(report_stub.get("work_style_hint"))
    next_step = _normalize_text(report_stub.get("next_step"))

    if dominant_focus and strength_hint and work_style_hint and next_step:
        return (
            f"{summary_intro}\n\n"
            "Ваш предварительный профиль:\n"
            f"- Что вам важно: {dominant_focus}\n"
            f"- Возможная сильная сторона: {strength_hint}\n"
            f"- Предпочтительный формат: {work_style_hint}\n\n"
            "Следующий шаг:\n"
            f"{next_step}"
        )

    return summary_intro



def render_expanded_report_text(expanded_report):
    intro = expanded_report.get("summary_intro")
    if not intro:
        intro = "Спасибо! Вот ваш расширенный предварительный разбор ✨"

    next_steps = expanded_report.get("next_steps")
    steps = []
    if next_steps:
        index = 1
        for item in next_steps:
            text = _normalize_text(item)
            if text:
                steps.append(f"{index}. {text}")
                index += 1

    if not steps:
        steps = [
            "1. Выберите небольшой практический шаг на ближайшую неделю.",
            "2. Отметьте, что дается легче и что вызывает интерес.",
        ]

    steps_block = "\n".join(steps)

    return (
        f"{intro}\n\n"
        "Что сейчас больше всего проявилось:\n"
        f"{expanded_report['interest_analysis']}\n\n"
        "Что можно считать сильной стороной:\n"
        f"{expanded_report['strength_analysis']}\n\n"
        "Какой формат деятельности может подойти:\n"
        f"{expanded_report['work_style_analysis']}\n\n"
        "На что стоит обратить внимание:\n"
        f"{expanded_report['growth_zone']}\n\n"
        "Ближайшие шаги:\n"
        f"{steps_block}"
    )
