from datetime import datetime, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Answer, TestSession

TEST_BLOCKS = [
    "Личность",
    "Интересы и увлечения",
    "Тип мышления",
    "Коммуникация",
    "Мотивация",
    "Стиль обучения",
    "Поведение в стрессе",
    "Ценности",
]

TEEN_TEST_QUESTIONS = [
    {
        "code": "q1_environment",
        "block": "Личность",
        "text": "В какой обстановке тебе комфортнее всего?",
        "options": [
            ("A", "Там, где можно быстро действовать и вести за собой"),
            ("B", "Там, где спокойно и есть время подумать"),
            ("C", "Там, где много живого общения и эмоций"),
            ("D", "Там, где есть порядок и понятные правила"),
        ],
    },
    {
        "code": "q2_emotions",
        "block": "Личность",
        "text": "Как ты обычно реагируешь на сильные эмоции?",
        "options": [
            ("A", "Беру себя в руки и сразу действую"),
            ("B", "Сначала анализирую, что происходит"),
            ("C", "Делюсь с близкими и проговариваю"),
            ("D", "Стараюсь стабилизировать ситуацию по шагам"),
        ],
    },
    {
        "code": "q3_new_ideas",
        "block": "Личность",
        "text": "Как ты относишься к новым идеям?",
        "options": [
            ("A", "Люблю запускать новое и проверять в деле"),
            ("B", "Сначала проверяю логику и риски"),
            ("C", "Люблю необычные и творческие идеи"),
            ("D", "Поддерживаю идеи, если есть чёткий план"),
        ],
    },
    {
        "code": "q4_self_tone",
        "block": "Личность",
        "text": "Какой стиль тебе ближе в повседневности?",
        "options": [
            ("A", "Энергичный, соревновательный"),
            ("B", "Спокойный, наблюдательный"),
            ("C", "Открытый, вдохновляющий"),
            ("D", "Собранный, организованный"),
        ],
    },
    {
        "code": "q5_interest_direction",
        "block": "Интересы и увлечения",
        "text": "Какие занятия тебя больше всего увлекают?",
        "options": [
            ("A", "Соревнования, лидерские и проектные активности"),
            ("B", "Исследования, анализ, логические задачи"),
            ("C", "Творчество, медиа, общение с людьми"),
            ("D", "Организация, системы, технологии и процессы"),
        ],
    },
    {
        "code": "q6_free_time_content",
        "block": "Интересы и увлечения",
        "text": "Как ты чаще проводишь свободное время?",
        "options": [
            ("A", "Активно: движение, мероприятия, участие"),
            ("B", "Спокойно: читаю, изучаю, наблюдаю"),
            ("C", "С людьми: творческие и социальные активности"),
            ("D", "Планирую дела, собираю проекты, структурирую"),
        ],
    },
    {
        "code": "q7_activity_preference",
        "block": "Интересы и увлечения",
        "text": "Какой формат хобби тебе ближе?",
        "options": [
            ("A", "Там, где есть результат и вызов"),
            ("B", "Там, где нужна глубина и внимательность"),
            ("C", "Там, где можно выражать себя и общаться"),
            ("D", "Там, где есть долгий замысел и структура"),
        ],
    },
    {
        "code": "q8_subject_preference",
        "block": "Интересы и увлечения",
        "text": "Какие школьные предметы обычно откликаются больше?",
        "options": [
            ("A", "Те, где нужно быстро принимать решения"),
            ("B", "Те, где важны логика и точность"),
            ("C", "Те, где можно обсуждать, создавать, выступать"),
            ("D", "Те, где ценятся порядок, метод и алгоритм"),
        ],
    },
    {
        "code": "q9_problem_solving",
        "block": "Тип мышления",
        "text": "Как ты чаще решаешь сложные задачи?",
        "options": [
            ("A", "Через действие и быстрые гипотезы"),
            ("B", "Через анализ данных и причин"),
            ("C", "Через креативные ходы и аналогии"),
            ("D", "Через пошаговую систему и план"),
        ],
    },
    {
        "code": "q10_decision_basis",
        "block": "Тип мышления",
        "text": "На что ты больше опираешься при выборе решения?",
        "options": [
            ("A", "На скорость и практический эффект"),
            ("B", "На факты и проверенные аргументы"),
            ("C", "На интуицию и ощущение людей"),
            ("D", "На стратегию и последствия наперёд"),
        ],
    },
    {
        "code": "q11_information_focus",
        "block": "Тип мышления",
        "text": "Какая информация для тебя наиболее важна?",
        "options": [
            ("A", "Что даст быстрый и заметный результат"),
            ("B", "Что точно подтверждено и обосновано"),
            ("C", "Что помогает понять людей и идеи"),
            ("D", "Что выстраивает целостную картину"),
        ],
    },
    {
        "code": "q12_planning_style",
        "block": "Тип мышления",
        "text": "Как тебе удобнее двигаться к цели?",
        "options": [
            ("A", "Через короткие рывки и дедлайны"),
            ("B", "Через продуманную аналитику"),
            ("C", "Через вдохновение и гибкость"),
            ("D", "Через детальный маршрут"),
        ],
    },
    {
        "code": "q13_group_role",
        "block": "Коммуникация",
        "text": "Какую роль ты чаще берёшь в группе?",
        "options": [
            ("A", "Инициирую и веду команду"),
            ("B", "Анализирую и уточняю детали"),
            ("C", "Поддерживаю атмосферу и идеи"),
            ("D", "Организую процесс и распределяю шаги"),
        ],
    },
    {
        "code": "q14_dialogue_style",
        "block": "Коммуникация",
        "text": "Какой стиль общения тебе ближе?",
        "options": [
            ("A", "Прямой, короткий, по делу"),
            ("B", "Спокойный, с вопросами и уточнениями"),
            ("C", "Тёплый, эмоциональный, вовлекающий"),
            ("D", "Структурный, с договорённостями"),
        ],
    },
    {
        "code": "q15_conflict_style",
        "block": "Коммуникация",
        "text": "Как ты обычно ведёшь себя в спорной ситуации?",
        "options": [
            ("A", "Сразу обсуждаю и двигаю к решению"),
            ("B", "Собираю факты и разбираю по пунктам"),
            ("C", "Сглаживаю напряжение и ищу контакт"),
            ("D", "Фиксирую правила и рамки разговора"),
        ],
    },
    {
        "code": "q16_public_expression",
        "block": "Коммуникация",
        "text": "Как ты чувствуешь себя в публичном выражении мнения?",
        "options": [
            ("A", "Уверенно, люблю выступать"),
            ("B", "Комфортно, если хорошо подготовился(ась)"),
            ("C", "Легко, когда есть эмоциональный отклик"),
            ("D", "Лучше, когда есть чёткая структура выступления"),
        ],
    },
    {
        "code": "q17_motivation_source",
        "block": "Мотивация",
        "text": "Что тебя больше мотивирует двигаться вперёд?",
        "options": [
            ("A", "Победа, достижение, признание"),
            ("B", "Понимание, компетентность, качество"),
            ("C", "Смысл, польза людям, вдохновение"),
            ("D", "Стабильный прогресс и долгосрочная цель"),
        ],
    },
    {
        "code": "q18_goal_horizon",
        "block": "Мотивация",
        "text": "Какие цели тебе проще удерживать?",
        "options": [
            ("A", "Амбициозные и с быстрым результатом"),
            ("B", "Точные и измеримые"),
            ("C", "Те, которые вдохновляют и связаны с людьми"),
            ("D", "Долгие и стратегические"),
        ],
    },
    {
        "code": "q19_success_criteria",
        "block": "Мотивация",
        "text": "Когда ты считаешь, что всё получилось?",
        "options": [
            ("A", "Когда виден сильный результат"),
            ("B", "Когда сделано качественно и без ошибок"),
            ("C", "Когда людям откликнулось и стало полезно"),
            ("D", "Когда выполнен план и закреплён эффект"),
        ],
    },
    {
        "code": "q20_effort_trigger",
        "block": "Мотивация",
        "text": "Что помогает не сдаваться в сложной задаче?",
        "options": [
            ("A", "Азарт и желание довести до победы"),
            ("B", "Рациональный разбор и дисциплина"),
            ("C", "Поддержка и вера в идею"),
            ("D", "План действий и контроль этапов"),
        ],
    },
    {
        "code": "q21_learning_channel",
        "block": "Стиль обучения",
        "text": "Как тебе легче всего усваивать новое?",
        "options": [
            ("A", "Через практику и действие"),
            ("B", "Через чтение, схемы и анализ"),
            ("C", "Через обсуждение и примеры"),
            ("D", "Через структурные курсы и систему"),
        ],
    },
    {
        "code": "q22_learning_pace",
        "block": "Стиль обучения",
        "text": "Какой темп обучения для тебя оптимален?",
        "options": [
            ("A", "Интенсивный, с быстрыми задачами"),
            ("B", "Ровный, с временем на осмысление"),
            ("C", "Гибкий, с обсуждением и обратной связью"),
            ("D", "Поэтапный, с заранее понятной программой"),
        ],
    },
    {
        "code": "q23_task_format",
        "block": "Стиль обучения",
        "text": "Какой формат учебных заданий тебе ближе?",
        "options": [
            ("A", "Практические кейсы и соревнование"),
            ("B", "Разборы, исследовательские задачи"),
            ("C", "Проекты с презентацией и общением"),
            ("D", "Пошаговые задания по чек-листу"),
        ],
    },
    {
        "code": "q24_feedback_style",
        "block": "Стиль обучения",
        "text": "Какая обратная связь помогает тебе больше всего?",
        "options": [
            ("A", "Короткая и сразу по результату"),
            ("B", "Подробная с аргументами"),
            ("C", "Поддерживающая и развивающая"),
            ("D", "Регулярная по чётким критериям"),
        ],
    },
    {
        "code": "q25_stress_reaction",
        "block": "Поведение в стрессе",
        "text": "Как ты чаще реагируешь в стрессовой ситуации?",
        "options": [
            ("A", "Собираюсь и действую быстро"),
            ("B", "Отхожу в сторону и анализирую"),
            ("C", "Ищу контакт и поддержку"),
            ("D", "Системно раскладываю проблему по шагам"),
        ],
    },
    {
        "code": "q26_stress_support",
        "block": "Поведение в стрессе",
        "text": "Что тебе помогает удержаться в сложный период?",
        "options": [
            ("A", "Фокус на конкретном действии"),
            ("B", "Пауза и спокойный анализ"),
            ("C", "Разговор с близкими людьми"),
            ("D", "Режим, план и предсказуемость"),
        ],
    },
    {
        "code": "q27_stress_recovery",
        "block": "Поведение в стрессе",
        "text": "Как ты обычно восстанавливаешься после напряжения?",
        "options": [
            ("A", "Через активность и новый импульс"),
            ("B", "Через тишину и личное пространство"),
            ("C", "Через общение и эмоциональную разрядку"),
            ("D", "Через возвращение к привычной системе"),
        ],
    },
    {
        "code": "q28_value_priority",
        "block": "Ценности",
        "text": "Что для тебя важнее при выборе направления?",
        "options": [
            ("A", "Возможность влиять и добиваться"),
            ("B", "Профессиональная глубина и экспертность"),
            ("C", "Польза людям и самовыражение"),
            ("D", "Стабильность и понятная траектория"),
        ],
    },
    {
        "code": "q29_team_value",
        "block": "Ценности",
        "text": "Какая среда тебе ближе всего?",
        "options": [
            ("A", "Среда вызова, ответственности и амбиций"),
            ("B", "Среда точности, знаний и объективности"),
            ("C", "Среда сотрудничества, идей и поддержки"),
            ("D", "Среда порядка, правил и долгого планирования"),
        ],
    },
    {
        "code": "q30_profession_choice",
        "block": "Ценности",
        "text": "Что для тебя критично при выборе будущей профессии?",
        "options": [
            ("A", "Динамика, рост и результат"),
            ("B", "Интеллектуальная сложность и точность"),
            ("C", "Люди, смысл и творчество"),
            ("D", "Системность, устойчивость и стратегия"),
        ],
    },
]

PARENT_TEST_QUESTIONS = [
    {
        "code": item["code"],
        "block": item["block"],
        "text": text,
        "options": item["options"],
    }
    for item, text in [
        (TEEN_TEST_QUESTIONS[0], "В какой обстановке Ваш ребёнок, по Вашим наблюдениям, чувствует себя наиболее комфортно?"),
        (TEEN_TEST_QUESTIONS[1], "Как Ваш ребёнок обычно реагирует на сильные эмоции?"),
        (TEEN_TEST_QUESTIONS[2], "Как Ваш ребёнок относится к новым идеям?"),
        (TEEN_TEST_QUESTIONS[3], "Какой стиль поведения у ребёнка чаще проявляется в повседневности?"),
        (TEEN_TEST_QUESTIONS[4], "Какие занятия, по Вашим наблюдениям, больше всего увлекают ребёнка?"),
        (TEEN_TEST_QUESTIONS[5], "Как ребёнок чаще проводит свободное время?"),
        (TEEN_TEST_QUESTIONS[6], "Какой формат хобби чаще всего выбирает ребёнок?"),
        (TEEN_TEST_QUESTIONS[7], "Какие школьные предметы обычно вызывают у ребёнка наибольший интерес?"),
        (TEEN_TEST_QUESTIONS[8], "Как ребёнок чаще решает сложные задачи?"),
        (TEEN_TEST_QUESTIONS[9], "На что ребёнок больше опирается при выборе решения?"),
        (TEEN_TEST_QUESTIONS[10], "Какая информация для ребёнка обычно наиболее значима?"),
        (TEEN_TEST_QUESTIONS[11], "Как ребёнку удобнее двигаться к цели?"),
        (TEEN_TEST_QUESTIONS[12], "Какую роль ребёнок чаще занимает в группе?"),
        (TEEN_TEST_QUESTIONS[13], "Какой стиль общения у ребёнка проявляется чаще?"),
        (TEEN_TEST_QUESTIONS[14], "Как ребёнок обычно ведёт себя в спорной ситуации?"),
        (TEEN_TEST_QUESTIONS[15], "Как ребёнок чувствует себя, когда нужно публично выразить мнение?"),
        (TEEN_TEST_QUESTIONS[16], "Что, по Вашим наблюдениям, сильнее всего мотивирует ребёнка?"),
        (TEEN_TEST_QUESTIONS[17], "Какие цели ребёнку проще удерживать?"),
        (TEEN_TEST_QUESTIONS[18], "Когда ребёнок обычно считает, что результат действительно достигнут?"),
        (TEEN_TEST_QUESTIONS[19], "Что помогает ребёнку не сдаваться в сложной задаче?"),
        (TEEN_TEST_QUESTIONS[20], "Как ребёнку легче усваивать новое?"),
        (TEEN_TEST_QUESTIONS[21], "Какой темп обучения обычно оптимален для ребёнка?"),
        (TEEN_TEST_QUESTIONS[22], "Какой формат учебных заданий чаще подходит ребёнку?"),
        (TEEN_TEST_QUESTIONS[23], "Какая обратная связь обычно помогает ребёнку больше всего?"),
        (TEEN_TEST_QUESTIONS[24], "Как ребёнок чаще реагирует в стрессовой ситуации?"),
        (TEEN_TEST_QUESTIONS[25], "Что помогает ребёнку удерживаться в сложный период?"),
        (TEEN_TEST_QUESTIONS[26], "Как ребёнок обычно восстанавливается после напряжения?"),
        (TEEN_TEST_QUESTIONS[27], "Что для ребёнка важнее при выборе направления?"),
        (TEEN_TEST_QUESTIONS[28], "Какая среда, по Вашим наблюдениям, ребёнку ближе всего?"),
        (TEEN_TEST_QUESTIONS[29], "Что для ребёнка критично при выборе будущей профессии?"),
    ]
]

# Backward-compatible alias: existing code may still import TEST_QUESTIONS.
TEST_QUESTIONS = TEEN_TEST_QUESTIONS


def get_questions_for_role(role):
    if role == "parent":
        return PARENT_TEST_QUESTIONS
    return TEEN_TEST_QUESTIONS


def _default_test_kind(role_snapshot):
    """Derive test_kind from role when not explicitly set."""
    if role_snapshot == "parent":
        return "parent_personal"
    return "teen_personal"


def get_questions_for_test_kind(test_kind):
    """Return the question list for a test_kind value."""
    if test_kind == "parent_personal":
        return PARENT_TEST_QUESTIONS
    return TEEN_TEST_QUESTIONS


async def create_test_session(
    session: AsyncSession,
    *,
    user_id,
    role_snapshot,
    test_kind=None,
) -> TestSession:
    kind = test_kind or _default_test_kind(role_snapshot)
    test_session = TestSession(
        user_id=user_id,
        role_snapshot=role_snapshot,
        test_kind=kind,
        status="active",
    )
    session.add(test_session)
    await session.commit()
    await session.refresh(test_session)
    return test_session


async def save_answer(
    session: AsyncSession,
    *,
    session_id,
    user_id,
    question_code,
    answer_value,
) -> Answer:
    answer = await save_answer_inplace(
        session,
        session_id=session_id,
        user_id=user_id,
        question_code=question_code,
        answer_value=answer_value,
    )
    await session.commit()
    await session.refresh(answer)
    return answer


async def save_answer_inplace(
    session: AsyncSession,
    *,
    session_id,
    user_id,
    question_code,
    answer_value,
) -> Answer:
    answer = Answer(
        session_id=session_id,
        user_id=user_id,
        question_code=question_code,
        answer_value=answer_value,
    )
    session.add(answer)
    return answer


async def complete_test_session(session: AsyncSession, *, session_id) -> TestSession:
    test_session = await complete_test_session_inplace(session, session_id=session_id)
    await session.commit()
    await session.refresh(test_session)
    return test_session


async def complete_test_session_inplace(session: AsyncSession, *, session_id) -> TestSession:
    result = await session.execute(select(TestSession).where(TestSession.id == session_id))
    test_session = result.scalar_one()
    test_session.status = "completed"
    test_session.completed_at = datetime.now(timezone.utc)
    return test_session


async def get_active_test_session(session: AsyncSession, *, user_id) -> TestSession | None:
    result = await session.execute(
        select(TestSession)
        .where(
            TestSession.user_id == user_id,
            TestSession.status == "active",
        )
        .order_by(desc(TestSession.id))
    )
    return result.scalars().first()


async def get_test_session_by_id(session: AsyncSession, *, session_id) -> TestSession | None:
    result = await session.execute(
        select(TestSession).where(TestSession.id == session_id)
    )
    return result.scalar_one_or_none()


async def count_answers_for_session(session: AsyncSession, *, session_id):
    result = await session.execute(
        select(func.count(Answer.id)).where(Answer.session_id == session_id)
    )
    count_value = result.scalar_one()
    return count_value + 0


async def cancel_test_session(session: AsyncSession, *, session_id) -> TestSession | None:
    test_session = await cancel_test_session_inplace(session, session_id=session_id)
    if test_session is None:
        return None

    await session.commit()
    await session.refresh(test_session)
    return test_session


async def cancel_test_session_inplace(session: AsyncSession, *, session_id) -> TestSession | None:
    result = await session.execute(select(TestSession).where(TestSession.id == session_id))
    test_session = result.scalar_one_or_none()
    if test_session is None:
        return None

    test_session.status = "cancelled"
    test_session.completed_at = datetime.now(timezone.utc)
    return test_session


async def restart_test_session(
    session: AsyncSession,
    *,
    user_id,
    role_snapshot,
    test_kind=None,
) -> TestSession:
    kind = test_kind or _default_test_kind(role_snapshot)
    active_session = await get_active_test_session(session, user_id=user_id)
    if active_session is not None:
        active_session.status = "cancelled"
        active_session.completed_at = datetime.now(timezone.utc)

    new_session = TestSession(
        user_id=user_id,
        role_snapshot=role_snapshot,
        test_kind=kind,
        status="active",
    )
    session.add(new_session)
    await session.commit()
    await session.refresh(new_session)
    return new_session
