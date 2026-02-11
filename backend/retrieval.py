"""
Retrieval functions for RAG context enhancement.

This module provides functions to retrieve relevant context from the vector store
based on user queries, and format it for inclusion in prompts.

Key design:
- SQLite is the source of truth.
- Chroma is used only as a semantic index that returns IDs.
- Retrieved IDs are hydrated back into full canonical records from SQLite.
"""

import json
import re
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from langchain_core.documents import Document
from .database import Function, Preset, Recipe, get_session
from .vector_store import search_vector_store_with_scores



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
    parts: List[str] = [f"Function: {func.name}"]

    if func.description:
        parts.append(f"Description: {func.description}")

    if func.params and func.params not in ("{}", "[]"):
        try:
            params = json.loads(func.params)
            if params:
                parts.append(f"Parameters: {params}")
        except json.JSONDecodeError:
            pass

    if func.examples and func.examples != "[]":
        try:
            examples = json.loads(func.examples)
            if examples:
                # Limit to a couple of examples to avoid bloating the prompt.
                parts.append(f"Examples: {examples[:2]}")
        except json.JSONDecodeError:
            pass

    if func.synonyms and func.synonyms != "[]":
        try:
            synonyms = json.loads(func.synonyms)
            if synonyms:
                parts.append(f"Also known as: {synonyms}")
        except json.JSONDecodeError:
            pass

    return "\n".join(parts)


MAX_RECIPE_CODE_CHARS = 600
MAX_PRESET_CODE_CHARS = 400


def _format_recipe_context(recipe: Recipe) -> str:
    parts: List[str] = [f"Recipe: {recipe.title}"]

    if recipe.description:
        parts.append(f"Description: {recipe.description}")

    if recipe.code:
        code = recipe.code
        if len(code) > MAX_RECIPE_CODE_CHARS:
            code = code[:MAX_RECIPE_CODE_CHARS] + "\n..."
        parts.append("Code:\n" + code)

    return "\n".join(parts)


def _format_preset_context(preset: Preset) -> str:
    parts: List[str] = [f"Preset: {preset.name}"]

    if preset.description:
        parts.append(f"Description: {preset.description}")

    if preset.code_example:
        code = preset.code_example
        if len(code) > MAX_PRESET_CODE_CHARS:
            code = code[:MAX_PRESET_CODE_CHARS] + "\n..."
        parts.append("Example:\n" + code)

    return "\n".join(parts)


def retrieve_relevant_context(
    query: str,
    k: int = 4,
    category_filter: Optional[str] = None,
    extra_function_names: Optional[List[str]] = None,
) -> str:
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
        Formatted context string ready for prompt injection.
    """
    MAX_FUNCTIONS = 3
    MAX_RECIPES = 2
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

    if extra_function_names:
        session = get_session()
        try:
            extra_ids: List[int] = []
            seen = set(function_ids_ordered)
            for name in extra_function_names[:MAX_FUNCTIONS]:
                func = session.query(Function).filter_by(name=name).first()
                if func and func.id not in seen:
                    extra_ids.append(func.id)
                    seen.add(func.id)
            function_ids_ordered = extra_ids + [
                fid for fid in function_ids_ordered if fid not in set(extra_ids)
            ]
        finally:
            session.close()

    if not docs_with_scores and not function_ids_ordered:
        return ""

    session = get_session()
    try:
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
                    block = _format_recipe_context(recipe)
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

        return "\n\n".join(context_parts) if context_parts else ""

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
