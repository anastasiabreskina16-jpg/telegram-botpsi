import json
import logging
from importlib import import_module

from app.config import settings
from app.services.report_service import normalize_answer_value

log = logging.getLogger(__name__)

AI_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary_intro": {"type": "string"},
        "dominant_focus": {"type": "string"},
        "strength_hint": {"type": "string"},
        "work_style_hint": {"type": "string"},
        "next_step": {"type": "string"},
    },
    "required": [
        "summary_intro",
        "dominant_focus",
        "strength_hint",
        "work_style_hint",
        "next_step",
    ],
    "additionalProperties": False,
}

EXPANDED_AI_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary_intro": {"type": "string"},
        "interest_analysis": {"type": "string"},
        "strength_analysis": {"type": "string"},
        "work_style_analysis": {"type": "string"},
        "growth_zone": {"type": "string"},
        "next_steps": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 4,
        },
    },
    "required": [
        "summary_intro",
        "interest_analysis",
        "strength_analysis",
        "work_style_analysis",
        "growth_zone",
        "next_steps",
    ],
    "additionalProperties": False,
}


def _extract_answers_map(answers):
    answer_map = {}
    for answer in answers:
        answer_map[answer.question_code] = answer.answer_value
    return answer_map


def _build_answers_by_code(answer_map):
    payload_map = {}
    for code, raw_value in answer_map.items():
        payload_map[code] = _safe_text(raw_value)
    return payload_map


def _safe_text(value):
    cleaned = normalize_answer_value(value)
    if cleaned is None:
        return ""
    return cleaned


def _validate_report_payload(payload):
    required = [
        "summary_intro",
        "dominant_focus",
        "strength_hint",
        "work_style_hint",
        "next_step",
    ]
    for key in required:
        value = payload.get(key)
        if not value or not f"{value}".strip():
            return False
    return True


def _count_items(items):
    total = 0
    for _ in items:
        total += 1
    return total


def _validate_expanded_report_payload(payload):
    required = [
        "summary_intro",
        "interest_analysis",
        "strength_analysis",
        "work_style_analysis",
        "growth_zone",
        "next_steps",
    ]

    for key in required:
        if key == "next_steps":
            continue
        value = payload.get(key)
        if not value or not f"{value}".strip():
            return False

    next_steps = payload.get("next_steps")
    if not next_steps:
        return False

    if not isinstance(next_steps, list):
        return False

    steps_count = _count_items(next_steps)
    if steps_count < 2 or steps_count > 4:
        return False

    for step in next_steps:
        if not step or not f"{step}".strip():
            return False

    return True


async def _request_chat_completion(*, system_prompt: str, user_prompt: str, max_tokens: int):
    openai_module = import_module("openai")
    AsyncOpenAI = openai_module.AsyncOpenAI
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout_seconds,
    )
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content
    return (content or "").strip()


async def generate_retention_nudge(
    *,
    segment: str,
    reminder_kind: str,
    phase: int | None,
    progress_percent: int,
    mismatch_hint: bool,
) -> str | None:
    if not settings.openai_enabled:
        return None

    if not settings.openai_api_key:
        return None

    try:
        import_module("openai")
    except Exception:
        log.exception("OpenAI SDK import failed for retention nudge. Falling back to local copy.")
        return None

    phase_label = phase if phase in (1, 2, 3, 4) else "unknown"
    system_prompt = (
        "Ты психолог-редактор уведомлений для Telegram-бота. "
        "Напиши одно короткое сообщение на русском языке: 1-2 предложения, без давления, без диагнозов, без манипуляции. "
        "Сообщение должно мягко вернуть человека в структурированный тест. "
        "Не используй кавычки, списки, эмодзи по умолчанию."
    )
    user_prompt = (
        "Данные пользователя:\n"
        f"- сегмент: {segment}\n"
        f"- тип напоминания: {reminder_kind}\n"
        f"- текущая фаза: {phase_label}\n"
        f"- прогресс: {progress_percent}%\n"
        f"- есть расхождения во взглядах: {'yes' if mismatch_hint else 'no'}\n\n"
        "Сформулируй одно уведомление для возврата в тест."
    )

    try:
        raw_text = await _request_chat_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=120,
        )
    except Exception:
        log.exception("OpenAI request failed for retention nudge. Falling back to local copy.")
        return None

    message = (raw_text or "").strip()
    if not message:
        return None

    return message[:280]


async def generate_ai_report(role, answers, *, comparison_context=None):
    if not settings.openai_enabled:
        return None

    if not settings.openai_api_key:
        log.warning("OpenAI enabled, but OPENAI_API_KEY is empty. Falling back to local summary.")
        return None

    try:
        openai_module = import_module("openai")
        AsyncOpenAI = openai_module.AsyncOpenAI
    except Exception:
        log.exception("OpenAI SDK import failed. Falling back to local summary.")
        return None

    answer_map = _extract_answers_map(answers)
    learning_env = _safe_text(answer_map.get("q1_environment"))
    legacy_interest = _safe_text(answer_map.get("q1_interest"))
    legacy_strength = _safe_text(answer_map.get("q2_strength"))
    legacy_format = _safe_text(answer_map.get("q3_format"))
    answers_by_code = _build_answers_by_code(answer_map)
    payload = {
        "role": role or "unknown",
        "q1_environment": learning_env,
        "answers_by_code": answers_by_code,
        # Backward-compatible fields for old sessions (if they still exist).
        "q1_interest": legacy_interest,
        "q2_strength": legacy_strength,
        "q3_format": legacy_format,
    }

    if isinstance(comparison_context, dict):
        payload["comparison"] = {
            "teen_type": comparison_context.get("teen_type"),
            "parent_type": comparison_context.get("parent_type"),
            "teen_scores": comparison_context.get("teen_scores"),
            "parent_scores": comparison_context.get("parent_scores"),
            "block_match_percent": comparison_context.get("block_match_percent"),
            "block_matches": comparison_context.get("block_matches") or [],
            "block_mismatches": comparison_context.get("block_mismatches") or [],
        }

    system_prompt = (
        "Вы формируете безопасный предварительный мини-итог по результатам личного теста подростка. "
        "Подросток отвечал про себя. "
        if role == "teen"
        else
        "Вы формируете предварительный отчёт о взгляде родителя на ребёнка по результатам личного теста. "
        "Родитель отвечал про ребёнка. "
    ) + (
        "Нельзя ставить диагнозы, делать жесткие выводы, обещать точную профориентацию. "
        "Пишите коротко, понятно и поддерживающе. Основывайтесь только на переданных ответах. "
        "Если переданы comparison-данные teen/parent, учитывайте их в формулировках совпадений и расхождений. "
        "Если данных мало, используйте аккуратные нейтральные формулировки."
    )

    user_prompt = (
        "Сформируй итог в точном JSON-формате по схеме. "
        "Не добавляй никаких полей, кроме требуемых схемой. "
        f"Данные: {json.dumps(payload, ensure_ascii=False)}"
    )

    try:
        raw_text = await _request_chat_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=400,
        )
        if not raw_text:
            log.warning("OpenAI returned empty content. Falling back to local summary.")
            return None

        parsed = json.loads(raw_text)
        try:
            parsed.get("summary_intro")
        except Exception:
            log.warning("OpenAI returned non-object JSON. Falling back to local summary.")
            return None

        if not _validate_report_payload(parsed):
            log.warning("OpenAI JSON failed required field validation. Falling back to local summary.")
            return None

        return parsed
    except Exception:
        log.exception("OpenAI request failed. Falling back to local summary.")
        return None


async def generate_expanded_ai_report(role, answers):
    if not settings.openai_enabled:
        return None

    if not settings.openai_api_key:
        log.warning("OpenAI enabled, but OPENAI_API_KEY is empty. Falling back to expanded stub message.")
        return None

    try:
        openai_module = import_module("openai")
        AsyncOpenAI = openai_module.AsyncOpenAI
    except Exception:
        log.exception("OpenAI SDK import failed. Falling back to expanded stub message.")
        return None

    answer_map = _extract_answers_map(answers)
    learning_env = _safe_text(answer_map.get("q1_environment"))
    legacy_interest = _safe_text(answer_map.get("q1_interest"))
    legacy_strength = _safe_text(answer_map.get("q2_strength"))
    legacy_format = _safe_text(answer_map.get("q3_format"))
    answers_by_code = _build_answers_by_code(answer_map)
    payload = {
        "role": role or "unknown",
        "q1_environment": learning_env,
        "answers_by_code": answers_by_code,
        # Backward-compatible fields for old sessions (if they still exist).
        "q1_interest": legacy_interest,
        "q2_strength": legacy_strength,
        "q3_format": legacy_format,
    }

    system_prompt = (
        "Вы формируете мягкий расширенный предварительный разбор по результатам личного теста подростка. "
        "Подросток отвечал про себя. "
        if role == "teen"
        else
        "Вы формируете мягкий расширенный предварительный разбор на основе взгляда родителя на ребёнка. "
        "Родитель отвечал про своего ребёнка. "
    ) + (
        "Это не диагноз, не психотерапия и не точная профориентация. "
        "Нельзя делать категоричные выводы и обещать точный выбор профессии. "
        "Пишите поддерживающе, понятно и кратко. Если данных мало, формулируйте осторожно и нейтрально."
    )

    user_prompt = (
        "Сформируй расширенный итог в точном JSON-формате по схеме. "
        "Не добавляй лишних полей. "
        f"Данные: {json.dumps(payload, ensure_ascii=False)}"
    )

    try:
        raw_text = await _request_chat_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=500,
        )
        if not raw_text:
            log.warning("OpenAI returned empty expanded content. Falling back to expanded stub message.")
            return None

        parsed = json.loads(raw_text)
        try:
            parsed.get("summary_intro")
        except Exception:
            log.warning("OpenAI returned non-object expanded JSON. Falling back to expanded stub message.")
            return None

        if not _validate_expanded_report_payload(parsed):
            log.warning("OpenAI expanded JSON failed validation. Falling back to expanded stub message.")
            return None

        return parsed
    except Exception:
        log.exception("OpenAI expanded request failed. Falling back to expanded stub message.")
        return None
