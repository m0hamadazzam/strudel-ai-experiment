"""
Copilot orchestration: conditional-prefetch -> generate -> validate -> repair -> patch.

This is the main entry point called by the FastAPI endpoint.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Generator

from dotenv import load_dotenv

from .context_window import window_conversation_history
from .database import AIInteraction, Function, get_session
from .generation import (
    generate_with_context,
    generate_with_context_stream,
    get_model,
    repair_with_context,
    repair_with_context_stream,
)
from .patch_utils import build_patch_operations, summarize_patch_operations
from .retrieval import (
    extract_function_names_from_query,
    get_all_preset_names,
    get_function_signatures,
    retrieve_context_for_functions,
    retrieve_preset_context,
    retrieve_relevant_context,
)
from .routing import (
    detect_sound_types,
    expand_query_with_aliases,
    should_enable_web_search,
    should_prefetch_kb,
)
from .schemas import (
    ChatRequest,
    ChatResponse,
    TokenUsage,
    ValidationResult,
)

backend_dir = Path(__file__).parent
load_dotenv(backend_dir / ".env")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Forbidden patterns (Node / non-Strudel)
# ---------------------------------------------------------------------------

FORBIDDEN_CODE_PATTERNS = (
    "require(",
    "import ",
    "process.",
    "__dirname",
    "module.exports",
)

# ---------------------------------------------------------------------------
# Identifier extraction (string-content-safe)
# ---------------------------------------------------------------------------

_RE_CALL_NAME = re.compile(r"\b([a-zA-Z_$][a-zA-Z0-9_]*)\s*\(")
_RE_METHOD_NAME = re.compile(r"\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\(")


def _strip_string_contents(code: str) -> str:
    """Remove string contents so regex doesn't match tokens inside mini-notation."""
    code = re.sub(r'"[^"]*"', '""', code)
    code = re.sub(r"'[^']*'", "''", code)
    code = re.sub(r"`[^`]*`", "``", code)
    return code


def _extract_called_identifiers(
    code: str,
) -> tuple[set[str], set[str]]:
    """Extract call/method names from code (skips string interiors)."""
    stripped = _strip_string_contents(code)
    names = set(_RE_CALL_NAME.findall(stripped))
    methods = set(_RE_METHOD_NAME.findall(stripped))
    return names, methods


# ---------------------------------------------------------------------------
# Allowed-names cache (DB function names + synonyms)
# ---------------------------------------------------------------------------

SAFE_JS_BUILTINS = frozenset({
    "Math", "parseInt", "parseFloat", "Number", "String",
    "Array", "Object", "JSON", "console", "Date",
    "floor", "ceil", "round", "abs", "min", "max",
    "random", "log", "pow", "sqrt", "sin", "cos",
    "map", "filter", "reduce", "forEach", "push",
    "join", "split", "slice", "concat", "includes",
    "keys", "values", "entries", "from", "isArray",
    "toString", "valueOf", "toFixed", "length",
    "set", "get", "has", "delete", "clear", "size",
})

_ALLOWED_FUNCTION_NAMES_CACHE: set[str] | None = None


def _get_allowed_function_names() -> set[str]:
    """Return set of all function names and synonyms in the KB. Cached."""
    global _ALLOWED_FUNCTION_NAMES_CACHE
    if _ALLOWED_FUNCTION_NAMES_CACHE is not None:
        return _ALLOWED_FUNCTION_NAMES_CACHE
    session = get_session()
    try:
        names: set[str] = set()
        for row in session.query(Function).all():
            if row.name:
                names.add(row.name)
            if row.synonyms and row.synonyms != "[]":
                try:
                    for syn in json.loads(row.synonyms) or []:
                        if isinstance(syn, str) and syn.strip():
                            names.add(syn.strip())
                except (json.JSONDecodeError, TypeError):
                    pass
        _ALLOWED_FUNCTION_NAMES_CACHE = names
        return names
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Validator (returns ALL errors, not just first)
# ---------------------------------------------------------------------------


def validate_generated_code(
    code: str,
    allowed_names: set[str] | None = None,
) -> ValidationResult:
    """Validate generated code. Returns a ValidationResult with all errors."""
    errors: list[str] = []
    invalid: list[str] = []

    for pattern in FORBIDDEN_CODE_PATTERNS:
        if pattern in code:
            errors.append(f"Disallowed pattern: {pattern}")

    if allowed_names and len(allowed_names) > 0:
        full_allowed = allowed_names | SAFE_JS_BUILTINS
        names, methods = _extract_called_identifiers(code)
        for name in names:
            if name not in full_allowed:
                errors.append(f"Unknown function: {name}")
                invalid.append(name)
        for method in methods:
            if method not in full_allowed:
                errors.append(f"Unknown method: .{method}()")
                invalid.append(method)

    return ValidationResult(
        ok=len(errors) == 0,
        errors=errors,
        invalid_names=invalid,
    )


# ---------------------------------------------------------------------------
# Sound / preset name validation
# ---------------------------------------------------------------------------

_RE_SOUND_STRINGS = re.compile(
    r"""\b(?:s|sound)\s*\(\s*(?:"([^"]*)"|'([^']*)'|`([^`]*)`)"""
)
_RE_SOUND_TOKEN = re.compile(r"[a-zA-Z][a-zA-Z0-9_]*")


def _extract_sound_names_from_code(code: str) -> set[str]:
    """Extract sound preset tokens from s("...") / sound("...") patterns."""
    sounds: set[str] = set()
    for m in _RE_SOUND_STRINGS.finditer(code):
        mini_notation = m.group(1) or m.group(2) or m.group(3)
        if mini_notation:
            tokens = _RE_SOUND_TOKEN.findall(mini_notation)
            sounds.update(tokens)
    return sounds


def _validate_sound_names(
    code: str,
    valid_presets: set[str],
) -> tuple[list[str], list[str]]:
    """Check that every sound token in s("...") exists in the presets table.

    Returns (error_messages, invalid_sound_names).
    """
    sounds = _extract_sound_names_from_code(code)
    errors: list[str] = []
    invalid: list[str] = []
    for name in sorted(sounds):
        if name not in valid_presets:
            errors.append(f"Unknown sound preset: {name}")
            invalid.append(name)
    return errors, invalid


# ---------------------------------------------------------------------------
# Function argument-count validation
# ---------------------------------------------------------------------------

_JS_KEYWORDS = frozenset({
    "if", "else", "for", "while", "do", "switch", "case", "break",
    "continue", "return", "function", "class", "new", "typeof",
    "instanceof", "void", "delete", "throw", "try", "catch",
    "finally", "const", "let", "var", "in", "of", "async", "await",
})

_RE_CALL_SITE = re.compile(r"([a-zA-Z_$][a-zA-Z0-9_]*)\s*\(")


def _count_args_at(code: str, open_paren: int) -> int:
    """Count comma-separated arguments starting at *open_paren*.

    Tracks balanced parens / brackets and skips string contents so that
    nested calls and mini-notation don't inflate the count.
    Returns -1 on unmatched parens (truncated code).
    """
    depth = 0
    n_args = 0
    has_content = False
    in_string: str | None = None
    i = open_paren

    while i < len(code):
        ch = code[i]

        if in_string:
            if ch == in_string and (i == 0 or code[i - 1] != "\\"):
                in_string = None
        elif ch in "\"'`":
            in_string = ch
            if depth == 1:
                has_content = True
        elif ch in "([{":
            if ch == "(" and depth == 0:
                pass
            elif depth == 1:
                has_content = True
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return n_args + (1 if has_content else 0)
        elif ch == "," and depth == 1:
            n_args += 1
            has_content = False
        elif depth == 1 and not ch.isspace():
            has_content = True

        i += 1
    return -1


def _parse_function_calls(code: str) -> list[tuple[str, int]]:
    """Extract (function_name, arg_count) for every call site in *code*."""
    stripped = _strip_string_contents(code)
    calls: list[tuple[str, int]] = []

    for m in _RE_CALL_SITE.finditer(stripped):
        name = m.group(1)
        if name in _JS_KEYWORDS:
            continue
        paren_pos = m.end() - 1
        n_args = _count_args_at(stripped, paren_pos)
        if n_args >= 0:
            calls.append((name, n_args))
    return calls


def _validate_function_args(
    code: str,
    sig_map: dict[str, tuple[int, int | None, str]],
) -> tuple[list[str], list[str]]:
    """Check that each call provides enough arguments.

    Only flags calls where actual_args < min_required_args.
    Returns (error_messages, function_names_with_errors).
    """
    calls = _parse_function_calls(code)
    errors: list[str] = []
    flagged: list[str] = []
    seen: set[str] = set()

    for name, actual in calls:
        if name not in sig_map:
            continue
        min_args, _max_args, hint = sig_map[name]
        if actual < min_args and name not in seen:
            seen.add(name)
            errors.append(
                f"{name}() called with {actual} arg(s), needs at least {min_args}. "
                f"Correct signature: {hint}"
            )
            flagged.append(name)
    return errors, flagged


# ---------------------------------------------------------------------------
# User content builder
# ---------------------------------------------------------------------------


def _build_user_content(request: ChatRequest) -> str:
    if request.current_code:
        return (
            f"Current code:\n{request.current_code}\n\n"
            f"User request: {request.message}\n"
        )
    return request.message


# ---------------------------------------------------------------------------
# Token usage helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Interaction logging
# ---------------------------------------------------------------------------


def _log_interaction(
    user_query: str,
    generated_code: str | None,
    response_time_ms: int,
    *,
    path_taken: str = "unknown",
    validation_passed_first: bool | None = None,
    repair_attempted: bool = False,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    session = get_session()
    try:
        session.add(
            AIInteraction(
                user_query=user_query,
                generated_code=generated_code,
                applied=0,
                response_time_ms=response_time_ms,
            )
        )
        session.commit()
    except Exception as e:
        logger.warning("Failed to log AI interaction: %s", e)
        session.rollback()
    finally:
        session.close()

    logger.info(
        "copilot request: path=%s validation_first_pass=%s repair=%s "
        "prompt_tokens=%d completion_tokens=%d latency_ms=%d",
        path_taken,
        validation_passed_first,
        repair_attempted,
        prompt_tokens,
        completion_tokens,
        response_time_ms,
    )


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _error_response(request: ChatRequest, explanation: str) -> ChatResponse:
    return ChatResponse(code=request.current_code or "", explanation=explanation)


def _build_success_response(
    request: ChatRequest,
    parsed,
    usage: TokenUsage,
    *,
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


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_code(request: ChatRequest) -> ChatResponse:
    """Generate-validate-repair orchestration."""
    if not os.getenv("OPENAI_API_KEY"):
        return _error_response(request, "Error: OPENAI_API_KEY not set in environment")

    start = time.perf_counter()
    user_query = request.message
    path_taken = "fast"

    try:
        # 1. Window conversation history
        history = window_conversation_history(request.conversation_history)

        # 2. Conditional KB prefetch
        pre_ctx = ""
        allowed_names = _get_allowed_function_names()
        if should_prefetch_kb(request.message, allowed_names):
            path_taken = "prefetch"
            query = expand_query_with_aliases(request.message)
            extra = extract_function_names_from_query(query)
            pre_ctx = retrieve_relevant_context(
                query, k=3, extra_function_names=extra[:3] if extra else None
            )

        # 3. Preset context: detect sound types and inject valid preset names
        sound_types, needs_synth = detect_sound_types(request.message)
        if sound_types or needs_synth:
            preset_ctx = retrieve_preset_context(
                sound_types, include_synths=needs_synth
            )
            if preset_ctx:
                pre_ctx = f"{pre_ctx}\n\n{preset_ctx}" if pre_ctx else preset_ctx

        # 4. Single LLM call (fast path)
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

        # 5. Validate functions AND sound preset names
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
            _log_interaction(
                user_query, draft.code, elapsed_ms,
                path_taken=path_taken,
                validation_passed_first=True,
                prompt_tokens=usage.input_tokens,
                completion_tokens=usage.output_tokens,
            )
            return _build_success_response(request, draft, usage)

        # 6. Repair path: build targeted context for invalid names
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
            _log_interaction(
                user_query, draft.code, elapsed_ms,
                path_taken=path_taken,
                validation_passed_first=False,
                repair_attempted=True,
                prompt_tokens=total_usage.input_tokens,
                completion_tokens=total_usage.output_tokens,
            )
            return _build_success_response(
                request, draft, total_usage, warning="Repair call failed; returning first draft."
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

        _log_interaction(
            user_query, fixed.code if result2.ok else draft.code, elapsed_ms,
            path_taken=path_taken,
            validation_passed_first=False,
            repair_attempted=True,
            prompt_tokens=total_usage.input_tokens,
            completion_tokens=total_usage.output_tokens,
        )

        if result2.ok:
            return _build_success_response(request, fixed, total_usage)

        return _build_success_response(
            request, fixed, total_usage,
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

        pre_ctx = ""
        allowed_names = _get_allowed_function_names()
        if should_prefetch_kb(request.message, allowed_names):
            path_taken = "prefetch"
            yield _status_event("Loading relevant Strudel reference docs.", "context")
            query = expand_query_with_aliases(request.message)
            extra = extract_function_names_from_query(query)
            pre_ctx = retrieve_relevant_context(
                query, k=3, extra_function_names=extra[:3] if extra else None
            )

        sound_types, needs_synth = detect_sound_types(request.message)
        if sound_types or needs_synth:
            yield _status_event("Checking valid sound presets and synth names.", "context")
            preset_ctx = retrieve_preset_context(
                sound_types, include_synths=needs_synth
            )
            if preset_ctx:
                pre_ctx = f"{pre_ctx}\n\n{preset_ctx}" if pre_ctx else preset_ctx

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
            _log_interaction(
                user_query, draft.code, elapsed_ms,
                path_taken=path_taken,
                validation_passed_first=True,
                prompt_tokens=usage.input_tokens,
                completion_tokens=usage.output_tokens,
            )
            yield _status_event("Building a patch preview for review.", "final")
            yield {
                "type": "final",
                "response": _dump_model(_build_success_response(request, draft, usage)),
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
            _log_interaction(
                user_query, draft.code, elapsed_ms,
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

        _log_interaction(
            user_query, fixed.code if result2.ok else draft.code, elapsed_ms,
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
                "response": _dump_model(_build_success_response(request, fixed, total_usage)),
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
                    warning="Some functions or sound presets may not be valid Strudel API.",
                )
            ),
        }

    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        _log_interaction(user_query, None, elapsed_ms, path_taken=path_taken)
        yield {"type": "error", "message": f"Error generating code: {str(e)}"}
