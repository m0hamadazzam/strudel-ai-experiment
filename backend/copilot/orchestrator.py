"""
Copilot orchestration: conditional-prefetch -> generate -> validate -> repair -> patch.

Main entry point called by the FastAPI endpoint.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Generator

from dotenv import load_dotenv

from backend.core.context_window import window_conversation_history
from backend.core.generation import (
    generate_with_context,
    generate_with_context_stream,
    get_model,
    repair_with_context,
    repair_with_context_stream,
)
from backend.core.routing import (
    detect_sound_types,
    expand_query_with_aliases,
    should_enable_web_search,
    should_prefetch_kb,
)
from backend.core.schemas import (
    ChatRequest,
    ChatResponse,
    TokenUsage,
    ValidationResult,
)
from backend.patching.patch_utils import build_patch_operations, summarize_patch_operations
from backend.rag.retrieval import (
    extract_function_names_from_query,
    get_all_preset_names,
    get_function_signatures,
    retrieve_context_for_functions,
    retrieve_preset_context,
    retrieve_preset_context_bundle,
    retrieve_relevant_context_bundle,
)

from .interactions import _log_interaction
from .validation import (
    _get_allowed_function_names,
    _extract_sound_names_from_code,
    _validate_function_args,
    _validate_sound_names,
    validate_generated_code,
)

backend_dir = Path(__file__).resolve().parent.parent
load_dotenv(backend_dir / ".env")


def _build_user_content(request: ChatRequest) -> str:
    if request.current_code:
        return (
            f"Current code:\n{request.current_code}\n\n"
            f"User request: {request.message}\n"
        )
    return request.message


_COST_PER_1K = {
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-5.1-codex-mini": (0.001, 0.003),
}


def _estimate_cost_usd(input_tokens: int, output_tokens: int) -> float | None:
    model = get_model()
    if model not in _COST_PER_1K:
        return None
    in_p, out_p = _COST_PER_1K[model]
    return (input_tokens / 1000.0) * in_p + (output_tokens / 1000.0) * out_p


def _sum_usage(*usages: dict | None) -> TokenUsage:
    """Combine one or more usage dicts into a single TokenUsage."""
    input_total = 0
    output_total = 0
    for u in usages:
        if not u or not isinstance(u, dict):
            continue
        input_total += int(u.get("input_tokens") or 0)
        output_total += int(u.get("output_tokens") or 0)
    total = input_total + output_total
    cost = _estimate_cost_usd(input_total, output_total)
    return TokenUsage(
        input_tokens=input_total,
        output_tokens=output_total,
        total_tokens=total,
        estimated_cost_usd=cost,
    )


def _error_response(request: ChatRequest, explanation: str) -> ChatResponse:
    return ChatResponse(code=request.current_code or "", explanation=explanation)


def _build_success_response(
    request: ChatRequest,
    parsed,
    usage: TokenUsage,
    *,
    interaction_id: int | None = None,
    warning: str | None = None,
) -> ChatResponse:
    code = parsed.code.strip()
    explanation = (
        (parsed.explanation or "").strip()
        if getattr(parsed, "explanation", None)
        else "Code generated successfully"
    )
    if warning:
        explanation = f"{explanation}\n\nWarning: {warning}"

    patch_ops = build_patch_operations(request.current_code or "", code)
    patch_stats = summarize_patch_operations(patch_ops)

    return ChatResponse(
        code=code,
        explanation=explanation or "Code generated successfully",
        patch_ops=patch_ops,
        patch_stats=patch_stats,
        usage=usage,
        interaction_id=interaction_id,
    )


def _dump_model(model) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _status_event(message: str, phase: str) -> dict:
    return {
        "type": "status",
        "phase": phase,
        "message": message,
    }


def generate_code(request: ChatRequest) -> ChatResponse:
    """Generate-validate-repair orchestration."""
    if not os.getenv("OPENAI_API_KEY"):
        return _error_response(request, "Error: OPENAI_API_KEY not set in environment")

    start = time.perf_counter()
    user_query = request.message
    path_taken = "fast"

    try:
        history = window_conversation_history(request.conversation_history)

        sound_types, needs_synth = detect_sound_types(request.message)

        pre_ctx = ""
        context_recipe_ids: list[int] = []
        allowed_names = _get_allowed_function_names()
        if should_prefetch_kb(request.message, allowed_names):
            path_taken = "prefetch"
            query = expand_query_with_aliases(request.message)
            extra = extract_function_names_from_query(query)
            retrieval_bundle = retrieve_relevant_context_bundle(
                query,
                k=3,
                extra_function_names=extra[:3] if extra else None,
                sound_types=sound_types or None,
            )
            pre_ctx = retrieval_bundle.text
            context_recipe_ids = retrieval_bundle.recipe_ids

        if sound_types or needs_synth:
            preset_bundle = retrieve_preset_context_bundle(
                sound_types, include_synths=needs_synth
            )
            if preset_bundle.text:
                pre_ctx = f"{pre_ctx}\n\n{preset_bundle.text}" if pre_ctx else preset_bundle.text

        enable_ws = should_enable_web_search(
            request.message, pre_ctx if pre_ctx else None
        )
        user_content = _build_user_content(request)
        draft, usage1 = generate_with_context(
            user_content=user_content,
            kb_context=pre_ctx,
            conversation_history=history,
            enable_web_search=enable_ws,
        )

        if draft is None:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            _log_interaction(user_query, None, elapsed_ms, path_taken=path_taken)
            return _error_response(
                request,
                "The model returned an unexpected response format. "
                "Please try again — this is usually a transient issue.",
            )

        result = validate_generated_code(draft.code, allowed_names)

        all_presets = get_all_preset_names()
        user_sounds = (
            _extract_sound_names_from_code(request.current_code)
            if request.current_code
            else set()
        )
        sound_errors, invalid_sounds = _validate_sound_names(
            draft.code, all_presets | user_sounds
        )
        if sound_errors:
            result = ValidationResult(
                ok=False,
                errors=result.errors + sound_errors,
                invalid_names=result.invalid_names + invalid_sounds,
            )

        sig_map = get_function_signatures()
        arg_errors, misused_fns = _validate_function_args(draft.code, sig_map)
        if arg_errors:
            result = ValidationResult(
                ok=False,
                errors=result.errors + arg_errors,
                invalid_names=result.invalid_names + misused_fns,
            )

        if result.ok:
            usage = _sum_usage(usage1)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            interaction_id = _log_interaction(
                user_query, draft.code, elapsed_ms,
                recipe_ids=context_recipe_ids,
                path_taken=path_taken,
                validation_passed_first=True,
                prompt_tokens=usage.input_tokens,
                completion_tokens=usage.output_tokens,
            )
            return _build_success_response(
                request,
                draft,
                usage,
                interaction_id=interaction_id,
            )

        path_taken = f"{path_taken}+repair"

        invalid_fn_only = [
            n for n in result.invalid_names
            if n not in set(invalid_sounds) and n not in set(misused_fns)
        ]
        repair_ctx_parts: list[str] = []
        if invalid_fn_only:
            fn_ctx = retrieve_context_for_functions(invalid_fn_only, k_per_fn=1)
            if fn_ctx:
                repair_ctx_parts.append(fn_ctx)
        if misused_fns:
            sig_ctx = retrieve_context_for_functions(misused_fns, k_per_fn=1)
            if sig_ctx:
                repair_ctx_parts.append(sig_ctx)
        if invalid_sounds:
            repair_types = sound_types or ["bd", "sd", "hh", "oh", "cp", "rim"]
            sound_repair_ctx = retrieve_preset_context(
                repair_types, include_synths=needs_synth
            )
            if sound_repair_ctx:
                repair_ctx_parts.append(sound_repair_ctx)

        repair_kb_ctx = "\n\n".join(repair_ctx_parts)

        fixed, usage2 = repair_with_context(
            user_content=user_content,
            draft_code=draft.code,
            kb_context=repair_kb_ctx,
            validation_errors=result.errors,
            conversation_history=history,
        )

        total_usage = _sum_usage(usage1, usage2)
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        if fixed is None:
            interaction_id = _log_interaction(
                user_query, draft.code, elapsed_ms,
                recipe_ids=context_recipe_ids,
                path_taken=path_taken,
                validation_passed_first=False,
                repair_attempted=True,
                prompt_tokens=total_usage.input_tokens,
                completion_tokens=total_usage.output_tokens,
            )
            return _build_success_response(
                request,
                draft,
                total_usage,
                interaction_id=interaction_id,
                warning="Repair call failed; returning first draft.",
            )

        result2 = validate_generated_code(fixed.code, allowed_names)
        sound_errors2, _ = _validate_sound_names(
            fixed.code, all_presets | user_sounds
        )
        if sound_errors2:
            result2 = ValidationResult(
                ok=False,
                errors=result2.errors + sound_errors2,
                invalid_names=result2.invalid_names,
            )
        arg_errors2, _ = _validate_function_args(fixed.code, sig_map)
        if arg_errors2:
            result2 = ValidationResult(
                ok=False,
                errors=result2.errors + arg_errors2,
                invalid_names=result2.invalid_names,
            )

        interaction_id = _log_interaction(
            user_query, fixed.code if result2.ok else draft.code, elapsed_ms,
            recipe_ids=context_recipe_ids,
            path_taken=path_taken,
            validation_passed_first=False,
            repair_attempted=True,
            prompt_tokens=total_usage.input_tokens,
            completion_tokens=total_usage.output_tokens,
        )

        if result2.ok:
            return _build_success_response(
                request,
                fixed,
                total_usage,
                interaction_id=interaction_id,
            )

        return _build_success_response(
            request,
            fixed,
            total_usage,
            interaction_id=interaction_id,
            warning="Some functions or sound presets may not be valid Strudel API.",
        )

    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        _log_interaction(user_query, None, elapsed_ms, path_taken=path_taken)
        return _error_response(request, f"Error generating code: {str(e)}")


def generate_code_stream(request: ChatRequest) -> Generator[dict, None, None]:
    """Streaming variant of generate_code() for live UI updates."""
    if not os.getenv("OPENAI_API_KEY"):
        yield {"type": "error", "message": "Error: OPENAI_API_KEY not set in environment"}
        return

    start = time.perf_counter()
    user_query = request.message
    path_taken = "fast"

    try:
        yield _status_event("Reviewing the current prompt and editor state.", "context")

        history = window_conversation_history(request.conversation_history)

        sound_types, needs_synth = detect_sound_types(request.message)

        pre_ctx = ""
        context_recipe_ids: list[int] = []
        allowed_names = _get_allowed_function_names()
        if should_prefetch_kb(request.message, allowed_names):
            path_taken = "prefetch"
            yield _status_event("Loading relevant Strudel reference docs.", "context")
            query = expand_query_with_aliases(request.message)
            extra = extract_function_names_from_query(query)
            retrieval_bundle = retrieve_relevant_context_bundle(
                query,
                k=3,
                extra_function_names=extra[:3] if extra else None,
                sound_types=sound_types or None,
            )
            pre_ctx = retrieval_bundle.text
            context_recipe_ids = retrieval_bundle.recipe_ids

        if sound_types or needs_synth:
            yield _status_event("Checking valid sound presets and synth names.", "context")
            preset_bundle = retrieve_preset_context_bundle(
                sound_types, include_synths=needs_synth
            )
            if preset_bundle.text:
                pre_ctx = f"{pre_ctx}\n\n{preset_bundle.text}" if pre_ctx else preset_bundle.text

        enable_ws = should_enable_web_search(
            request.message, pre_ctx if pre_ctx else None
        )
        if enable_ws:
            yield _status_event(
                "Allowing a limited web lookup if local docs are not enough.",
                "context",
            )

        user_content = _build_user_content(request)

        yield _status_event("Generating the first draft.", "generation")
        draft, usage1 = yield from generate_with_context_stream(
            user_content=user_content,
            kb_context=pre_ctx,
            conversation_history=history,
            enable_web_search=enable_ws,
        )

        if draft is None:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            _log_interaction(user_query, None, elapsed_ms, path_taken=path_taken)
            yield {
                "type": "error",
                "message": (
                    "The model returned an unexpected response format. "
                    "Please try again — this is usually a transient issue."
                ),
            }
            return

        yield _status_event(
            "Validating Strudel functions, sound presets, and argument counts.",
            "validation",
        )
        result = validate_generated_code(draft.code, allowed_names)

        all_presets = get_all_preset_names()
        user_sounds = (
            _extract_sound_names_from_code(request.current_code)
            if request.current_code
            else set()
        )
        sound_errors, invalid_sounds = _validate_sound_names(
            draft.code, all_presets | user_sounds
        )
        if sound_errors:
            result = ValidationResult(
                ok=False,
                errors=result.errors + sound_errors,
                invalid_names=result.invalid_names + invalid_sounds,
            )

        sig_map = get_function_signatures()
        arg_errors, misused_fns = _validate_function_args(draft.code, sig_map)
        if arg_errors:
            result = ValidationResult(
                ok=False,
                errors=result.errors + arg_errors,
                invalid_names=result.invalid_names + misused_fns,
            )

        if result.ok:
            usage = _sum_usage(usage1)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            interaction_id = _log_interaction(
                user_query, draft.code, elapsed_ms,
                recipe_ids=context_recipe_ids,
                path_taken=path_taken,
                validation_passed_first=True,
                prompt_tokens=usage.input_tokens,
                completion_tokens=usage.output_tokens,
            )
            yield _status_event("Building a patch preview for review.", "final")
            yield {
                "type": "final",
                "response": _dump_model(
                    _build_success_response(
                        request,
                        draft,
                        usage,
                        interaction_id=interaction_id,
                    )
                ),
            }
            return

        path_taken = f"{path_taken}+repair"
        yield _status_event(
            "The first draft needs repair against the Strudel reference.",
            "repair",
        )

        invalid_fn_only = [
            n for n in result.invalid_names
            if n not in set(invalid_sounds) and n not in set(misused_fns)
        ]
        repair_ctx_parts: list[str] = []
        if invalid_fn_only:
            fn_ctx = retrieve_context_for_functions(invalid_fn_only, k_per_fn=1)
            if fn_ctx:
                repair_ctx_parts.append(fn_ctx)
        if misused_fns:
            sig_ctx = retrieve_context_for_functions(misused_fns, k_per_fn=1)
            if sig_ctx:
                repair_ctx_parts.append(sig_ctx)
        if invalid_sounds:
            repair_types = sound_types or ["bd", "sd", "hh", "oh", "cp", "rim"]
            sound_repair_ctx = retrieve_preset_context(
                repair_types, include_synths=needs_synth
            )
            if sound_repair_ctx:
                repair_ctx_parts.append(sound_repair_ctx)

        repair_kb_ctx = "\n\n".join(repair_ctx_parts)

        fixed, usage2 = yield from repair_with_context_stream(
            user_content=user_content,
            draft_code=draft.code,
            kb_context=repair_kb_ctx,
            validation_errors=result.errors,
            conversation_history=history,
        )

        total_usage = _sum_usage(usage1, usage2)
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        if fixed is None:
            interaction_id = _log_interaction(
                user_query, draft.code, elapsed_ms,
                recipe_ids=context_recipe_ids,
                path_taken=path_taken,
                validation_passed_first=False,
                repair_attempted=True,
                prompt_tokens=total_usage.input_tokens,
                completion_tokens=total_usage.output_tokens,
            )
            yield _status_event(
                "Repair failed, returning the first draft with a warning.",
                "final",
            )
            yield {
                "type": "final",
                "response": _dump_model(
                    _build_success_response(
                        request,
                        draft,
                        total_usage,
                        interaction_id=interaction_id,
                        warning="Repair call failed; returning first draft.",
                    )
                ),
            }
            return

        yield _status_event("Re-validating the repaired draft.", "validation")
        result2 = validate_generated_code(fixed.code, allowed_names)
        sound_errors2, _ = _validate_sound_names(
            fixed.code, all_presets | user_sounds
        )
        if sound_errors2:
            result2 = ValidationResult(
                ok=False,
                errors=result2.errors + sound_errors2,
                invalid_names=result2.invalid_names,
            )
        arg_errors2, _ = _validate_function_args(fixed.code, sig_map)
        if arg_errors2:
            result2 = ValidationResult(
                ok=False,
                errors=result2.errors + arg_errors2,
                invalid_names=result2.invalid_names,
            )

        interaction_id = _log_interaction(
            user_query, fixed.code if result2.ok else draft.code, elapsed_ms,
            recipe_ids=context_recipe_ids,
            path_taken=path_taken,
            validation_passed_first=False,
            repair_attempted=True,
            prompt_tokens=total_usage.input_tokens,
            completion_tokens=total_usage.output_tokens,
        )

        if result2.ok:
            yield _status_event("Repair succeeded. Building a patch preview.", "final")
            yield {
                "type": "final",
                "response": _dump_model(
                    _build_success_response(
                        request,
                        fixed,
                        total_usage,
                        interaction_id=interaction_id,
                    )
                ),
            }
            return

        yield _status_event(
            "Repair finished, but some API names still need a manual check.",
            "final",
        )
        yield {
            "type": "final",
            "response": _dump_model(
                _build_success_response(
                    request,
                    fixed,
                    total_usage,
                    interaction_id=interaction_id,
                    warning="Some functions or sound presets may not be valid Strudel API.",
                )
            ),
        }

    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        _log_interaction(user_query, None, elapsed_ms, path_taken=path_taken)
        yield {"type": "error", "message": f"Error generating code: {str(e)}"}
