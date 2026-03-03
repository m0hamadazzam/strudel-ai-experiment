from __future__ import annotations

import json
from collections import Counter, defaultdict

from backend.db.models import FunctionRelationship, Recipe


def _parse_related_function_ids(raw: str | None) -> list[int]:
    if not raw or raw in ("[]", "null"):
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    out: list[int] = []
    for value in parsed:
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            continue
    return out


def rebuild_function_relationships(
    session,
    *,
    max_related_per_function: int = 8,
) -> dict[str, int]:
    """Rebuild function co-occurrence edges from recipe.related_functions."""
    pair_counts: Counter[tuple[int, int]] = Counter()
    by_source: defaultdict[int, list[tuple[int, int]]] = defaultdict(list)

    recipes = session.query(Recipe.related_functions).all()
    for recipe in recipes:
        related_ids = sorted(set(_parse_related_function_ids(recipe.related_functions)))
        if len(related_ids) < 2:
            continue
        for source_id in related_ids:
            for target_id in related_ids:
                if source_id == target_id:
                    continue
                pair_counts[(source_id, target_id)] += 1

    for (source_id, target_id), count in pair_counts.items():
        by_source[source_id].append((target_id, count))

    session.query(FunctionRelationship).delete(synchronize_session=False)

    created = 0
    for source_id, related in by_source.items():
        related.sort(key=lambda item: (-item[1], item[0]))
        max_count = related[0][1]
        for target_id, count in related[:max_related_per_function]:
            session.add(
                FunctionRelationship(
                    function_id=source_id,
                    related_function_id=target_id,
                    relationship_type="recipe_cooccurrence",
                    strength=count / max_count if max_count else 0.0,
                )
            )
            created += 1

    session.commit()
    return {"relationships": created, "sources": len(by_source)}


def get_related_function_ids(
    session,
    function_ids: list[int],
    *,
    limit_per_function: int = 3,
) -> list[int]:
    """Return related function IDs ordered by source priority then edge strength."""
    if not function_ids:
        return []

    if session.query(FunctionRelationship.id).first() is None:
        rebuild_function_relationships(session)

    rows = (
        session.query(FunctionRelationship)
        .filter(FunctionRelationship.function_id.in_(function_ids))
        .order_by(
            FunctionRelationship.function_id.asc(),
            FunctionRelationship.strength.desc(),
            FunctionRelationship.related_function_id.asc(),
        )
        .all()
    )

    source_order = {fid: index for index, fid in enumerate(function_ids)}
    seen: set[int] = set(function_ids)
    counts_by_source: defaultdict[int, int] = defaultdict(int)
    ordered: list[tuple[int, int, float]] = []

    for row in rows:
        if row.related_function_id in seen:
            continue
        if counts_by_source[row.function_id] >= limit_per_function:
            continue
        counts_by_source[row.function_id] += 1
        seen.add(row.related_function_id)
        ordered.append(
            (
                source_order.get(row.function_id, len(source_order)),
                row.related_function_id,
                row.strength or 0.0,
            )
        )

    ordered.sort(key=lambda item: (item[0], -item[2], item[1]))
    return [related_id for _, related_id, _ in ordered]
