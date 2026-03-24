"""AI-powered pair-dialogue report service."""
from __future__ import annotations

import builtins
import json
import logging
from importlib import import_module

from app.config import settings
from app.services.pair_analysis_service import BLOCK_LABELS
from app.services.pair_test_service import get_pair_session_by_id_for_update, save_persisted_ai_report

log = logging.getLogger(__name__)

def _build_prompt(
    diff: builtins.dict[builtins.str, builtins.dict[builtins.str, builtins.object]],
    previous_diff: builtins.dict[builtins.str, builtins.dict[builtins.str, builtins.object]] | None,
    teen_scores: builtins.dict[builtins.str, builtins.int],
    parent_scores: builtins.dict[builtins.str, builtins.int],
) -> builtins.str:
    # Convert raw block keys to human labels in the data sent to GPT
    labeled: builtins.dict[builtins.str, builtins.dict[builtins.str, builtins.object]] = {}
    for block, data in diff.items():
        label = BLOCK_LABELS.get(block, block)
        labeled[label] = {
            "подросток": data["teen"],
            "родитель": data["parent"],
            "разница": data["diff"],
            "статус": data["status"],
        }

    teen_labeled = {BLOCK_LABELS.get(k, k): v for k, v in teen_scores.items()}
    parent_labeled = {BLOCK_LABELS.get(k, k): v for k, v in parent_scores.items()}

    data_json = json.dumps(
        {
            "баллы_подростка": teen_labeled,
            "баллы_родителя": parent_labeled,
            "сравнение_по_блокам": labeled,
        },
        ensure_ascii=False,
        indent=2,
    )

    previous_json = "это первый результат пользователя"
    if previous_diff:
        previous_labeled: builtins.dict[builtins.str, builtins.dict[builtins.str, builtins.object]] = {}
        for block, data in previous_diff.items():
            label = BLOCK_LABELS.get(block, block)
            previous_labeled[label] = {
                "подросток": data.get("teen"),
                "родитель": data.get("parent"),
                "разница": data.get("diff"),
                "статус": data.get("status"),
            }
        previous_json = json.dumps(previous_labeled, ensure_ascii=False, indent=2)

    return f"""Ты семейный психолог.

Вот текущий результат:
{data_json}

Вот предыдущий результат:
{previous_json}

Проанализируй:
1. Что изменилось
2. Где стало лучше
3. Где есть риск
4. Дай 2 короткие рекомендации

Правила:
- без психологических терминов
- без диагнозов
- пиши как живой человек
- простые слова
- не более 8 предложений"""


async def build_ai_report(
    diff: builtins.dict[builtins.str, builtins.dict[builtins.str, builtins.object]],
    teen_scores: builtins.dict[builtins.str, builtins.int],
    parent_scores: builtins.dict[builtins.str, builtins.int],
    previous_diff: builtins.dict[builtins.str, builtins.dict[builtins.str, builtins.object]] | None = None,
) -> builtins.str | None:
    if not settings.openai_enabled:
        return None

    if not settings.openai_api_key:
        log.warning("OpenAI enabled but OPENAI_API_KEY is empty — skipping AI pair report.")
        return None

    try:
        openai_module = import_module("openai")
        AsyncOpenAI = openai_module.AsyncOpenAI
    except builtins.Exception:
        log.exception("OpenAI SDK import failed — skipping AI pair report.")
        return None

    prompt = _build_prompt(diff, previous_diff, teen_scores, parent_scores)

    try:
        client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_timeout_seconds,
        )
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=400,
        )
        text: builtins.str = response.choices[0].message.content or ""
        text = text.strip()
        if not text:
            log.warning("OpenAI returned empty content for AI pair report.")
            return None

        return text

    except builtins.Exception:
        log.exception("OpenAI request failed for AI pair report — using fallback.")
        return None


async def get_or_create_ai_report(
    session,
    *,
    pair_session_id: builtins.int,
    diff: builtins.dict[builtins.str, builtins.dict[builtins.str, builtins.object]],
    teen_scores: builtins.dict[builtins.str, builtins.int],
    parent_scores: builtins.dict[builtins.str, builtins.int],
    previous_diff: builtins.dict[builtins.str, builtins.dict[builtins.str, builtins.object]] | None = None,
) -> builtins.str | None:
    pair_session = await get_pair_session_by_id_for_update(session, pair_session_id=pair_session_id)
    if pair_session is None:
        return None
    if pair_session.ai_report_generated and pair_session.ai_report:
        return pair_session.ai_report

    ai_text = await build_ai_report(
        diff,
        teen_scores,
        parent_scores,
        previous_diff=previous_diff,
    )
    if not ai_text:
        return None

    await save_persisted_ai_report(
        session,
        pair_session_id=pair_session_id,
        ai_report=ai_text,
    )
    return ai_text
