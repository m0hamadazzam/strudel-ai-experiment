"""
Retrieval functions for RAG context enhancement.

This module provides functions to retrieve relevant context from the vector store
based on user queries, and format it for inclusion in prompts.

Key design:
- SQLite is the source of truth.
- Chroma is used only as a semantic index that returns IDs.
- Retrieved IDs are hydrated back into full canonical records from SQLite.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from langchain_core.documents import Document

from backend.db.models import Function, Preset, Recipe
from backend.db.session import get_session

from .relationship_utils import get_related_function_ids
from .vector_store import search_vector_store_with_scores


@dataclass
class RetrievedContext:
    text: str = ""
    function_ids: list[int] = field(default_factory=list)
    recipe_ids: list[int] = field(default_factory=list)
    preset_ids: list[int] = field(default_factory=list)



def _group_ids_by_type(
    docs_with_scores: Sequence[Tuple[Document, float]],
) -> Tuple[List[int], List[int], List[int]]:
    """
    Group retrieved vector documents by backing DB type, deduplicated by ID.

    Returns:
        (function_ids_ordered, recipe_ids_ordered, preset_ids_ordered)
        where each list preserves the original relevance ordering (by score)
        and contains no duplicates.
    """
    function_ids_ordered: List[int] = []
    recipe_ids_ordered: List[int] = []
    preset_ids_ordered: List[int] = []

    seen_functions: Set[int] = set()
    seen_recipes: Set[int] = set()
    seen_presets: Set[int] = set()

    for doc, _score in docs_with_scores:
        metadata = getattr(doc, "metadata", {}) or {}
        doc_type = metadata.get("type")

        if doc_type == "function" and "function_id" in metadata:
            try:
                fid = int(metadata["function_id"])
            except (TypeError, ValueError):
                continue
            if fid not in seen_functions:
                seen_functions.add(fid)
                function_ids_ordered.append(fid)
        elif doc_type == "recipe" and "recipe_id" in metadata:
            try:
                rid = int(metadata["recipe_id"])
            except (TypeError, ValueError):
                continue
            if rid not in seen_recipes:
                seen_recipes.add(rid)
                recipe_ids_ordered.append(rid)
        elif doc_type == "preset" and "preset_id" in metadata:
            try:
                pid = int(metadata["preset_id"])
            except (TypeError, ValueError):
                continue
            if pid not in seen_presets:
                seen_presets.add(pid)
                preset_ids_ordered.append(pid)

    return function_ids_ordered, recipe_ids_ordered, preset_ids_ordered


def _hydrate_functions(session, ids: Iterable[int]) -> List[Function]:
    if not ids:
        return []
    return list(session.query(Function).filter(Function.id.in_(list(ids))).all())


def _hydrate_recipes(session, ids: Iterable[int]) -> List[Recipe]:
    if not ids:
        return []
    return list(session.query(Recipe).filter(Recipe.id.in_(list(ids))).all())


def _hydrate_presets(session, ids: Iterable[int]) -> List[Preset]:
    if not ids:
        return []
    return list(session.query(Preset).filter(Preset.id.in_(list(ids))).all())


def _format_function_context(func: Function) -> str:
    """Compact function doc: signature-style header + one example."""
    params_str = ""
    if func.params and func.params not in ("{}", "[]"):
        try:
            params = json.loads(func.params)
            if isinstance(params, list) and params:
                sigs = []
                for p in params[:4]:
                    if isinstance(p, dict):
                        name = p.get("name", "?")
                        ptype = p.get("type", "")
                        sigs.append(f"{name}: {ptype}" if ptype else name)
                    elif isinstance(p, str):
                        sigs.append(p)
                params_str = ", ".join(sigs)
        except json.JSONDecodeError:
            pass

    header = f"{func.name}({params_str})"
    if func.description:
        header += f" -- {func.description}"

    parts: List[str] = [header]

    if func.examples and func.examples != "[]":
        try:
            examples = json.loads(func.examples)
            if examples:
                ex = examples[0] if isinstance(examples[0], str) else str(examples[0])
                parts.append(f"  Ex: {ex[:200]}")
        except json.JSONDecodeError:
            pass

    if func.synonyms and func.synonyms != "[]":
        try:
            synonyms = json.loads(func.synonyms)
            if synonyms:
                parts.append(f"  Aliases: {', '.join(str(s) for s in synonyms)}")
        except json.JSONDecodeError:
            pass

    return "\n".join(parts)


MAX_RECIPE_CODE_CHARS = 600
MAX_PRESET_CODE_CHARS = 400
_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "how",
    "i",
    "in",
    "is",
    "it",
    "like",
    "make",
    "me",
    "my",
    "of",
    "on",
    "please",
    "some",
    "that",
    "the",
    "this",
    "to",
    "with",
}
_BEGINNER_HINTS = {"beginner", "easy", "simple", "basic"}
_ADVANCED_HINTS = {"advanced", "complex", "expert"}
_INTERMEDIATE_HINTS = {"intermediate"}


def _parse_json_list(raw: str | None) -> list:
    if not raw or raw in ("[]", "{}", "null"):
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _recipe_function_ids(recipe: Recipe) -> set[int]:
    ids: set[int] = set()
    for value in _parse_json_list(recipe.related_functions):
        try:
            ids.add(int(value))
        except (TypeError, ValueError):
            continue
    return ids


def _query_tokens(text: str) -> set[str]:
    tokens = {
        token
        for token in re.findall(r"\b[a-z][a-z0-9_+-]{2,}\b", text.lower())
        if token not in _QUERY_STOPWORDS
    }
    return tokens


def _query_difficulty(text: str) -> str | None:
    tokens = _query_tokens(text)
    if tokens & _BEGINNER_HINTS:
        return "beginner"
    if tokens & _ADVANCED_HINTS:
        return "advanced"
    if tokens & _INTERMEDIATE_HINTS:
        return "intermediate"
    return None


def _score_recipe(
    recipe: Recipe,
    *,
    vector_rank: dict[int, int],
    preferred_function_ids: set[int],
    query_tokens: set[str],
    difficulty_hint: str | None,
    sound_types: list[str] | None,
) -> float:
    score = 0.0

    if recipe.id in vector_rank:
        score += max(0.5, 3.0 - (0.35 * vector_rank[recipe.id]))

    related_function_overlap = len(_recipe_function_ids(recipe) & preferred_function_ids)
    if related_function_overlap:
        score += related_function_overlap * 2.5

    if difficulty_hint and recipe.difficulty == difficulty_hint:
        score += 1.0

    haystack = " ".join(
        filter(
            None,
            [
                recipe.title,
                recipe.description,
                recipe.category,
                recipe.tags,
            ],
        )
    ).lower()
    code_lower = (recipe.code or "").lower()
    for token in query_tokens:
        if token in haystack:
            score += 0.6
        elif token in code_lower:
            score += 0.25

    if sound_types:
        for sound_type in sound_types:
            if re.search(rf"(?<![a-z0-9_]){re.escape(sound_type)}(?![a-z0-9_])", code_lower):
                score += 0.9

    return score


def _rank_recipe_ids(
    session,
    *,
    ordered_vector_recipe_ids: list[int],
    preferred_function_ids: list[int],
    query: str,
    sound_types: list[str] | None,
    max_recipes: int,
) -> list[int]:
    vector_rank = {
        recipe_id: rank for rank, recipe_id in enumerate(ordered_vector_recipe_ids)
    }
    query_tokens = _query_tokens(query)
    difficulty_hint = _query_difficulty(query)
    preferred_set = set(preferred_function_ids)

    scored: list[tuple[float, int]] = []
    for recipe in session.query(Recipe).all():
        score = _score_recipe(
            recipe,
            vector_rank=vector_rank,
            preferred_function_ids=preferred_set,
            query_tokens=query_tokens,
            difficulty_hint=difficulty_hint,
            sound_types=sound_types,
        )
        if score <= 0:
            continue
        scored.append((score, recipe.id))

    scored.sort(key=lambda item: (-item[0], vector_rank.get(item[1], 9999), item[1]))
    return [recipe_id for _, recipe_id in scored[:max_recipes]]


def _format_recipe_context(
    recipe: Recipe,
    *,
    function_id_to_name: dict[int, str] | None = None,
) -> str:
    header = f"Recipe: {recipe.title}"
    if recipe.difficulty:
        header += f" [{recipe.difficulty}]"
    if recipe.description:
        header += f" -- {recipe.description}"
    parts: List[str] = [header]
    if function_id_to_name:
        related_names = [
            function_id_to_name[func_id]
            for func_id in _recipe_function_ids(recipe)
            if func_id in function_id_to_name
        ]
        if related_names:
            parts.append(f"  Uses: {', '.join(related_names[:8])}")
    if recipe.code:
        code = recipe.code
        if len(code) > MAX_RECIPE_CODE_CHARS:
            code = code[:MAX_RECIPE_CODE_CHARS] + "\n..."
        parts.append(code)
    return "\n".join(parts)


def _format_preset_context(preset: Preset) -> str:
    header = f"Preset: {preset.name}"
    if preset.description:
        header += f" -- {preset.description}"
    parts: List[str] = [header]
    if preset.code_example:
        code = preset.code_example
        if len(code) > MAX_PRESET_CODE_CHARS:
            code = code[:MAX_PRESET_CODE_CHARS] + "\n..."
        parts.append(code)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Preset name cache + targeted preset retrieval
# ---------------------------------------------------------------------------

_ALL_PRESET_NAMES_CACHE: Optional[Set[str]] = None


def get_all_preset_names() -> Set[str]:
    """Return the full set of valid preset names from the DB. Cached."""
    global _ALL_PRESET_NAMES_CACHE
    if _ALL_PRESET_NAMES_CACHE is not None:
        return _ALL_PRESET_NAMES_CACHE
    session = get_session()
    try:
        names: Set[str] = set()
        for row in session.query(Preset.name).all():
            if row.name:
                names.add(row.name)
        _ALL_PRESET_NAMES_CACHE = names
        return names
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Function signature cache (for argument-count validation)
# ---------------------------------------------------------------------------

_FUNCTION_SIGNATURES_CACHE: Optional[Dict[str, Tuple[int, Optional[int], str]]] = None


def get_function_signatures() -> Dict[str, Tuple[int, Optional[int], str]]:
    """Return cached map of function_name -> (min_args, max_args, hint).

    *hint* is a compact string like ``when(binary_pat, func) e.g. .when(…)``
    that can be embedded in repair error messages.

    min_args heuristic:
      - Callback-param functions: all params required (the callback is never
        optional — that's the whole point of the function).
      - Non-callback functions with 3+ params: allow one optional trailing
        param (min = n - 1) to avoid false positives on functions like
        ``echo``, ``euclidRot``, ``adsr`` that may accept fewer args.
      - Non-callback functions with ≤2 params: all required.
      - Variadic (``variable: true``): min = 1, max = None.
    """
    global _FUNCTION_SIGNATURES_CACHE
    if _FUNCTION_SIGNATURES_CACHE is not None:
        return _FUNCTION_SIGNATURES_CACHE

    session = get_session()
    try:
        sig_map: Dict[str, Tuple[int, Optional[int], str]] = {}
        for func in session.query(Function).all():
            if not func.name or not func.params or func.params in ("[]", "{}", "null", ""):
                continue
            try:
                params = json.loads(func.params)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(params, list) or not params:
                continue

            n_params = len(params)
            pnames = [
                p.get("name", "?") for p in params if isinstance(p, dict)
            ]
            variadic = any(
                isinstance(p, dict) and p.get("variable", False)
                for p in params
            )
            has_callback = any(
                isinstance(p, dict)
                and "function" in str(p.get("type", {}).get("names", []))
                for p in params
            )

            # Build compact hint: "when(binary_pat, func) e.g. <first line>"
            sig_part = f"{func.name}({', '.join(pnames)})"
            example_line = ""
            if func.examples and func.examples != "[]":
                try:
                    exs = json.loads(func.examples)
                    if exs and isinstance(exs[0], str):
                        example_line = exs[0].split("\n")[0].strip()[:100]
                except (json.JSONDecodeError, TypeError):
                    pass
            hint = f"{sig_part}. Example: {example_line}" if example_line else sig_part

            if variadic:
                sig_map[func.name] = (1, None, hint)
            elif has_callback:
                sig_map[func.name] = (n_params, n_params, hint)
            elif n_params >= 3:
                sig_map[func.name] = (n_params - 1, n_params, hint)
            else:
                sig_map[func.name] = (n_params, n_params, hint)

        _FUNCTION_SIGNATURES_CACHE = sig_map
        return sig_map
    finally:
        session.close()


_SUFFIX_LABELS: Dict[str, str] = {
    "bd": "Kick/bass drum",
    "sd": "Snare",
    "hh": "Hi-hat (closed)",
    "oh": "Hi-hat (open)",
    "cp": "Clap",
    "rim": "Rimshot",
    "lt": "Low tom",
    "mt": "Mid tom",
    "ht": "High tom",
    "cr": "Crash cymbal",
    "rd": "Ride cymbal",
    "cb": "Cowbell",
    "sh": "Shaker",
    "tb": "Tambourine",
}

MAX_BANK_VARIANTS_PER_TYPE = 6


def retrieve_preset_context_bundle(
    sound_types: List[str],
    include_synths: bool = False,
    max_per_type: int = MAX_BANK_VARIANTS_PER_TYPE,
) -> RetrievedContext:
    """Build a compact list of valid preset names for the given sound types.

    For each drum suffix (e.g. "sd") returns the base name plus popular bank
    variants (e.g. RolandTR808_sd, RolandTR909_sd).  Token-efficient: just
    names, no full docs.
    """
    session = get_session()
    try:
        sections: List[str] = []
        preset_ids: list[int] = []
        seen_preset_ids: set[int] = set()

        for stype in sound_types:
            label = _SUFFIX_LABELS.get(stype, stype)
            names: List[str] = [stype]

            bank_presets = (
                session.query(Preset)
                .filter(Preset.name.like(f"%\\_{stype}", escape="\\"))
                .order_by(Preset.usage_count.desc())
                .limit(max_per_type)
                .all()
            )
            for preset in bank_presets:
                if preset.name != stype:
                    names.append(preset.name)
                if preset.id not in seen_preset_ids:
                    seen_preset_ids.add(preset.id)
                    preset_ids.append(preset.id)

            sections.append(f"{label} ({stype}): {', '.join(names)}")

        if include_synths:
            synth_presets = (
                session.query(Preset)
                .filter(Preset.category == "synth")
                .order_by(Preset.usage_count.desc(), Preset.name.asc())
                .all()
            )
            if synth_presets:
                synth_names = [preset.name for preset in synth_presets]
                for preset in synth_presets:
                    if preset.id not in seen_preset_ids:
                        seen_preset_ids.add(preset.id)
                        preset_ids.append(preset.id)
                sections.append(f"Synths: {', '.join(synth_names)}")

        if not sections:
            return RetrievedContext()

        header = (
            "=== Valid Sound Presets ===\n"
            'Use ONLY these names inside s("...") patterns:'
        )
        return RetrievedContext(
            text=header + "\n" + "\n".join(sections),
            preset_ids=preset_ids,
        )
    finally:
        session.close()


def retrieve_preset_context(
    sound_types: List[str],
    include_synths: bool = False,
    max_per_type: int = MAX_BANK_VARIANTS_PER_TYPE,
) -> str:
    return retrieve_preset_context_bundle(
        sound_types,
        include_synths=include_synths,
        max_per_type=max_per_type,
    ).text


def retrieve_relevant_context_bundle(
    query: str,
    k: int = 4,
    category_filter: Optional[str] = None,
    extra_function_names: Optional[List[str]] = None,
    sound_types: Optional[List[str]] = None,
) -> RetrievedContext:
    """
    Retrieve relevant context from the knowledge base for a given query.

    Flow:
    1. Optionally resolve extra_function_names to function IDs (by-name lookup).
    2. Query Chroma to get candidate documents + scores.
    3. Deduplicate by backing DB IDs; merge extra function IDs with semantic (no duplicates).
    4. Hydrate full records from SQLite.
    5. Apply per-type caps and an overall context size budget.
    6. Format a compact, high-signal context string.

    Args:
        query: User query string.
        k: Number of vector results to retrieve (default: 4).
        category_filter: Optional category to filter by.
        extra_function_names: Optional list of function names to include (e.g. from query).

    Returns:
        A RetrievedContext containing the formatted context string and the IDs
        that backed it.
    """
    MAX_FUNCTIONS = 3
    MAX_RECIPES = 3
    MAX_PRESETS = 2
    MAX_CONTEXT_CHARS = 8000
    SCORE_THRESHOLD = 0.7

    filter_dict = {"category": category_filter} if category_filter else None

    docs_with_scores = search_vector_store_with_scores(
        query=query,
        k=k,
        filter_dict=filter_dict,
        score_threshold=SCORE_THRESHOLD,
    )

    function_ids_ordered, recipe_ids_ordered, preset_ids_ordered = _group_ids_by_type(
        docs_with_scores
    )

    session = get_session()
    try:
        extra_ids: List[int] = []
        if extra_function_names:
            seen = set(function_ids_ordered)
            for name in extra_function_names[:MAX_FUNCTIONS]:
                func = session.query(Function).filter_by(name=name).first()
                if func and func.id not in seen:
                    extra_ids.append(func.id)
                    seen.add(func.id)

        related_ids = get_related_function_ids(
            session,
            extra_ids or function_ids_ordered[:MAX_FUNCTIONS],
            limit_per_function=2,
        )

        ordered_function_candidates = extra_ids + related_ids + function_ids_ordered
        seen_function_ids: set[int] = set()
        function_ids_ordered = []
        for fid in ordered_function_candidates:
            if fid in seen_function_ids:
                continue
            seen_function_ids.add(fid)
            function_ids_ordered.append(fid)

        recipe_ids_ordered = _rank_recipe_ids(
            session,
            ordered_vector_recipe_ids=recipe_ids_ordered,
            preferred_function_ids=function_ids_ordered[:MAX_FUNCTIONS],
            query=query,
            sound_types=sound_types,
            max_recipes=MAX_RECIPES,
        )

        if not docs_with_scores and not function_ids_ordered and not recipe_ids_ordered:
            return RetrievedContext()

        # Hydrate from SQLite, then re-order according to the ordered ID lists.
        functions = _hydrate_functions(session, function_ids_ordered)
        recipes = _hydrate_recipes(session, recipe_ids_ordered)
        presets = _hydrate_presets(session, preset_ids_ordered)

        func_by_id: Dict[int, Function] = {f.id: f for f in functions}
        recipe_by_id: Dict[int, Recipe] = {r.id: r for r in recipes}
        preset_by_id: Dict[int, Preset] = {p.id: p for p in presets}

        ordered_functions: List[Function] = [
            func_by_id[fid] for fid in function_ids_ordered if fid in func_by_id
        ][:MAX_FUNCTIONS]
        ordered_recipes: List[Recipe] = [
            recipe_by_id[rid] for rid in recipe_ids_ordered if rid in recipe_by_id
        ][:MAX_RECIPES]
        ordered_presets: List[Preset] = [
            preset_by_id[pid] for pid in preset_ids_ordered if pid in preset_by_id
        ][:MAX_PRESETS]

        related_function_ids: set[int] = set()
        for recipe in ordered_recipes:
            related_function_ids.update(_recipe_function_ids(recipe))
        recipe_function_ids = sorted(related_function_ids)
        recipe_function_names = {
            func.id: func.name for func in _hydrate_functions(session, recipe_function_ids)
        }

        context_parts: List[str] = []
        total_len = 0

        # Helper to append a block respecting the global character budget.
        def _append_block(block: str) -> bool:
            nonlocal total_len
            if not block:
                return True
            projected = total_len + len(block)
            if projected > MAX_CONTEXT_CHARS:
                return False
            context_parts.append(block)
            total_len = projected
            return True

        # Functions section.
        if ordered_functions:
            header = "=== Relevant Functions ==="
            if _append_block(header):
                for func in ordered_functions:
                    block = _format_function_context(func)
                    if not _append_block("\n" + block):
                        break

        # Recipes section.
        if ordered_recipes:
            header = "\n=== Relevant Recipes ==="
            if _append_block(header):
                for recipe in ordered_recipes:
                    block = _format_recipe_context(
                        recipe,
                        function_id_to_name=recipe_function_names,
                    )
                    if not _append_block("\n" + block):
                        break

        # Presets section.
        if ordered_presets:
            header = "\n=== Relevant Presets ==="
            if _append_block(header):
                for preset in ordered_presets:
                    block = _format_preset_context(preset)
                    if not _append_block("\n" + block):
                        break

        return RetrievedContext(
            text="\n\n".join(context_parts) if context_parts else "",
            function_ids=[func.id for func in ordered_functions],
            recipe_ids=[recipe.id for recipe in ordered_recipes],
            preset_ids=[preset.id for preset in ordered_presets],
        )

    finally:
        session.close()


def retrieve_context_for_functions(
    function_names: List[str],
    k_per_fn: int = 1,
) -> str:
    """Retrieve KB docs for specific function names (used in repair flow).

    Does a vector search per name, hydrates from SQLite, and returns
    compact formatted context for only the requested functions.
    """
    MAX_NAMES = 5
    session = get_session()
    try:
        parts: List[str] = []
        seen_ids: Set[int] = set()
        for name in function_names[:MAX_NAMES]:
            func = session.query(Function).filter_by(name=name).first()
            if func and func.id not in seen_ids:
                seen_ids.add(func.id)
                parts.append(_format_function_context(func))
                continue
            docs = search_vector_store_with_scores(name, k=k_per_fn, score_threshold=0.5)
            fids, _, _ = _group_ids_by_type(docs)
            for fid in fids[:1]:
                if fid not in seen_ids:
                    seen_ids.add(fid)
                    hydrated = _hydrate_functions(session, [fid])
                    if hydrated:
                        parts.append(_format_function_context(hydrated[0]))
        return "\n\n".join(parts)
    finally:
        session.close()


_FUNCTION_NAME_INDEX: Optional[Dict[str, str]] = None
_FUNCTION_NAME_PATTERN: Optional[re.Pattern[str]] = None


def _build_function_name_index() -> Tuple[Dict[str, str], Optional[re.Pattern[str]]]:
    """
    Build an in-memory index of function names and synonyms for detection.

    Returns:
        (name_map, regex_pattern)

        name_map: maps lowercased token -> canonical function name.
        regex_pattern: compiled regex matching any known name/synonym with
            word boundaries and optional parentheses.
    """
    session = get_session()
    name_map: Dict[str, str] = {}

    try:
        functions: List[Function] = list(session.query(Function).all())
        for func in functions:
            canonical = func.name
            if not canonical:
                continue

            name_map[canonical.lower()] = canonical

            if func.synonyms and func.synonyms != "[]":
                try:
                    synonyms = json.loads(func.synonyms)
                    for syn in synonyms or []:
                        if not isinstance(syn, str):
                            continue
                        key = syn.lower()
                        # Prefer explicit name over synonym on collision.
                        name_map.setdefault(key, canonical)
                except json.JSONDecodeError:
                    continue
    finally:
        session.close()

    if not name_map:
        return {}, None

    # Build a regex that matches any known name/synonym with word boundaries,
    # optionally followed by parentheses:  stack  or  stack( ... )
    escaped_names = sorted(
        {re.escape(name) for name in name_map.keys()},
        key=len,
        reverse=True,
    )
    pattern_str = r"\b(" + "|".join(escaped_names) + r")\b\s*\(?"
    try:
        compiled = re.compile(pattern_str, flags=re.IGNORECASE)
    except re.error:
        compiled = None

    return name_map, compiled


def extract_function_names_from_query(query: str) -> List[str]:
    """
    Extract potential function names from a user query.

    Uses the function and synonym data from the SQLite database instead of a
    hardcoded list, and is robust to punctuation such as ``stack(...)``.

    Args:
        query: User query string.

    Returns:
        List of canonical function names detected in the query.
    """
    global _FUNCTION_NAME_INDEX, _FUNCTION_NAME_PATTERN

    if _FUNCTION_NAME_INDEX is None or _FUNCTION_NAME_PATTERN is None:
        _FUNCTION_NAME_INDEX, _FUNCTION_NAME_PATTERN = _build_function_name_index()

    if not _FUNCTION_NAME_INDEX or _FUNCTION_NAME_PATTERN is None:
        return []

    matches = _FUNCTION_NAME_PATTERN.findall(query)
    found: List[str] = []

    for raw in matches:
        key = raw.lower()
        canonical = _FUNCTION_NAME_INDEX.get(key)
        if canonical and canonical not in found:
            found.append(canonical)

    return found


def canonicalize_function_names(names: Iterable[str]) -> List[str]:
    """Map function names or aliases to canonical KB names."""
    global _FUNCTION_NAME_INDEX, _FUNCTION_NAME_PATTERN

    if _FUNCTION_NAME_INDEX is None:
        _FUNCTION_NAME_INDEX, _FUNCTION_NAME_PATTERN = _build_function_name_index()

    if not _FUNCTION_NAME_INDEX:
        return []

    canonical_names: list[str] = []
    seen: set[str] = set()
    for name in names:
        canonical = _FUNCTION_NAME_INDEX.get(str(name).lower())
        if canonical and canonical not in seen:
            seen.add(canonical)
            canonical_names.append(canonical)
    return canonical_names
