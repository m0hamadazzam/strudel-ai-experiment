"""
Interaction logging and feedback: metadata, usage stats, record_interaction_feedback.
"""

from __future__ import annotations

import json
import logging

from backend.core.schemas import InteractionFeedbackResponse
from backend.db.models import AIInteraction, Function, Preset, Recipe
from backend.db.session import get_session

from .validation import (
    _extract_canonical_function_names_from_code,
    _extract_sound_names_from_code,
)

logger = logging.getLogger(__name__)


def _build_interaction_metadata(
    generated_code: str | None,
    *,
    recipe_ids: list[int] | None = None,
) -> str:
    metadata = {
        "functions": _extract_canonical_function_names_from_code(generated_code or ""),
        "presets": sorted(_extract_sound_names_from_code(generated_code or "")),
        "recipes": sorted(set(recipe_ids or [])),
    }
    return json.dumps(metadata)


def _parse_interaction_metadata(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _success_weight(status: str | None) -> float:
    if status == "accepted":
        return 1.0
    if status == "partial":
        return 0.5
    return 0.0


def _recompute_usage_stats(session) -> None:
    function_attempts: dict[str, int] = {}
    function_success: dict[str, float] = {}
    function_accepts: dict[str, int] = {}
    preset_accepts: dict[str, int] = {}
    recipe_accepts: dict[int, int] = {}
    recipe_success: dict[int, int] = {}

    for interaction in session.query(AIInteraction).all():
        metadata = _parse_interaction_metadata(interaction.functions_used)
        functions = {
            str(name)
            for name in metadata.get("functions", [])
            if isinstance(name, str) and name
        }
        presets = {
            str(name)
            for name in metadata.get("presets", [])
            if isinstance(name, str) and name
        }
        recipe_ids = {
            int(recipe_id)
            for recipe_id in metadata.get("recipes", [])
            if isinstance(recipe_id, int) or str(recipe_id).isdigit()
        }

        status = interaction.user_feedback
        weight = _success_weight(status)
        accepted_like = status in {"accepted", "partial"}

        for name in functions:
            if status:
                function_attempts[name] = function_attempts.get(name, 0) + 1
                function_success[name] = function_success.get(name, 0.0) + weight
            if accepted_like:
                function_accepts[name] = function_accepts.get(name, 0) + 1

        if accepted_like:
            for name in presets:
                preset_accepts[name] = preset_accepts.get(name, 0) + 1
            for recipe_id in recipe_ids:
                recipe_accepts[recipe_id] = recipe_accepts.get(recipe_id, 0) + 1
                if status == "accepted":
                    recipe_success[recipe_id] = recipe_success.get(recipe_id, 0) + 1

    for function in session.query(Function).all():
        function.usage_count = function_accepts.get(function.name, 0)
        attempts = function_attempts.get(function.name, 0)
        function.success_rate = (
            function_success.get(function.name, 0.0) / attempts if attempts else None
        )

    for preset in session.query(Preset).all():
        preset.usage_count = preset_accepts.get(preset.name, 0)

    for recipe in session.query(Recipe).all():
        recipe.usage_count = recipe_accepts.get(recipe.id, 0)
        recipe.success_count = recipe_success.get(recipe.id, 0)


def record_interaction_feedback(
    interaction_id: int,
    *,
    status: str,
) -> InteractionFeedbackResponse:
    session = get_session()
    try:
        interaction = session.get(AIInteraction, interaction_id)
        if interaction is None:
            raise ValueError(f"Unknown interaction: {interaction_id}")

        interaction.applied = 1 if status in {"accepted", "partial"} else 0
        interaction.user_feedback = status
        session.flush()
        _recompute_usage_stats(session)
        session.commit()
        return InteractionFeedbackResponse(ok=True)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _log_interaction(
    user_query: str,
    generated_code: str | None,
    response_time_ms: int,
    *,
    recipe_ids: list[int] | None = None,
    path_taken: str = "unknown",
    validation_passed_first: bool | None = None,
    repair_attempted: bool = False,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> int | None:
    session = get_session()
    interaction_id: int | None = None
    try:
        interaction = AIInteraction(
            user_query=user_query,
            generated_code=generated_code,
            applied=0,
            functions_used=_build_interaction_metadata(
                generated_code,
                recipe_ids=recipe_ids,
            ),
            response_time_ms=response_time_ms,
        )
        session.add(interaction)
        session.commit()
        interaction_id = interaction.id
    except Exception as e:
        logger.warning("Failed to log AI interaction: %s", e)
        session.rollback()
    finally:
        session.close()

    logger.info(
        "copilot request: path=%s validation_first_pass=%s repair=%s "
        "prompt_tokens=%d completion_tokens=%d latency_ms=%d interaction_id=%s",
        path_taken,
        validation_passed_first,
        repair_attempted,
        prompt_tokens,
        completion_tokens,
        response_time_ms,
        interaction_id,
    )
    return interaction_id
