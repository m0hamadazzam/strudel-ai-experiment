"""
Code validation: forbidden patterns, function/sound names, and argument counts.
"""

from __future__ import annotations

import json
import re

from backend.core.schemas import ValidationResult
from backend.db.models import Function
from backend.db.session import get_session
from backend.rag.retrieval import canonicalize_function_names

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
    """Blank out string literal contents so regexes do not match tokens inside them."""
    code = re.sub(r'"[^"]*"', '""', code)
    code = re.sub(r"'[^']*'", "''", code)
    code = re.sub(r"`[^`]*`", "``", code)
    return code


def _extract_called_identifiers(
    code: str,
) -> tuple[set[str], set[str]]:
    """Extract function and method names from code, skipping anything inside strings."""
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
    """Return the cached set of all known Strudel function names and synonyms."""
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
    """Validate generated code and return a `ValidationResult` containing all errors."""
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
    """Extract sound preset tokens from ``s("...")`` / ``sound("...")`` call patterns."""
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
# Canonical function names from code (used by interactions for metadata)
# ---------------------------------------------------------------------------


def _extract_canonical_function_names_from_code(code: str) -> list[str]:
    """Return canonical Strudel function names inferred from a code snippet."""
    names, methods = _extract_called_identifiers(code)
    return canonicalize_function_names(sorted(names | methods))
