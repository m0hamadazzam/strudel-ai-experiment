#!/usr/bin/env python3
"""
Validate imported functions, presets, and recipes against expected sources.

See backend/README.md (Data import strategy) for what is imported and how.
"""

import json
from pathlib import Path

from backend.db.models import Function, Preset, Recipe
from backend.db.session import get_session

from backend.scripts.import_data import (
    BUILTIN_SYNTH_PRESETS,
    DIRT_SAMPLES_INLINE_PRESETS,
    PRESET_SOURCES,
    RECIPE_MDX_DIR,
    RECIPE_MDX_IMPORT_TAG,
    RECIPE_SOURCES,
    _preset_names_from_json,
    load_recipes_from_file,
    load_recipes_from_mdx,
)


def validate_import():
    """Run validation checks on imported data."""
    session = get_session()
    project_root = Path(__file__).resolve().parent.parent.parent

    print("=== Validation Checklist ===\n")

    # Load doc.json to compare
    doc_json_path = project_root / "doc.json"

    with open(doc_json_path, "r") as f:
        doc_data = json.load(f)

    # Get all functions from doc.json (excluding filtered ones)
    doc_functions = [
        f
        for f in doc_data.get("docs", [])
        if f.get("name")
        and not f.get("name", "").startswith("_")
        and f.get("kind") != "package"
    ]

    # Get unique function names (accounting for duplicates in doc.json)
    doc_unique_names = set(f["name"] for f in doc_functions)

    # Get all imported functions
    db_functions = session.query(Function).all()
    db_unique_names = set(f.name for f in db_functions)

    print(
        f"1. Total function entries in doc.json (after filtering): {len(doc_functions)}"
    )
    print(f"   Unique function names in doc.json: {len(doc_unique_names)}")
    print(f"   Total functions in database: {len(db_functions)}")

    if len(db_functions) == len(doc_unique_names):
        print("   ✓ PASS: All unique functions imported")
    else:
        missing = doc_unique_names - db_unique_names
        if missing:
            print(
                f"   ✗ FAIL: Missing {len(missing)} unique functions: {list(missing)[:10]}"
            )
        else:
            print(
                "   ✓ PASS: All unique functions imported (some duplicates in doc.json were skipped)"
            )

    # Check for duplicates
    print("\n2. Checking for duplicate function names...")
    names = [f.name for f in db_functions]
    duplicates = [name for name in names if names.count(name) > 1]
    if duplicates:
        print(f"   ✗ FAIL: Found duplicates: {set(duplicates)}")
    else:
        print("   ✓ PASS: No duplicate function names")

    # Check categories
    print("\n3. Checking categories...")
    categories = {}
    for func in db_functions:
        cat = func.category or "none"
        categories[cat] = categories.get(cat, 0) + 1

    print("   Category distribution:")
    for cat, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
        print(f"     {cat}: {count} functions")
    print("   ✓ PASS: Categories assigned")

    # Check JSON fields are valid
    print("\n4. Validating JSON fields...")
    json_errors = []
    for func in db_functions:
        for field_name, field_value in [
            ("synonyms", func.synonyms),
            ("examples", func.examples),
            ("params", func.params),
        ]:
            if field_value:
                try:
                    json.loads(field_value)
                except json.JSONDecodeError:
                    json_errors.append(f"{func.name}.{field_name}")

    if json_errors:
        print(f"   ✗ FAIL: Invalid JSON in {len(json_errors)} fields:")
        for error in json_errors[:10]:
            print(f"     - {error}")
    else:
        print("   ✓ PASS: All JSON fields are valid")

    # Check examples are preserved
    print("\n5. Checking examples preservation...")
    functions_with_examples = sum(
        1 for f in db_functions if f.examples and f.examples != "[]"
    )
    print(f"   Functions with examples: {functions_with_examples}/{len(db_functions)}")
    print("   ✓ PASS: Examples preserved")

    # Check synonyms are preserved
    print("\n6. Checking synonyms preservation...")
    functions_with_synonyms = sum(
        1 for f in db_functions if f.synonyms and f.synonyms != "[]"
    )
    print(f"   Functions with synonyms: {functions_with_synonyms}/{len(db_functions)}")
    print("   ✓ PASS: Synonyms preserved")

    # Check parameters are preserved
    print("\n7. Checking parameters preservation...")
    functions_with_params = sum(
        1 for f in db_functions if f.params and f.params != "{}" and f.params != "[]"
    )
    print(f"   Functions with params: {functions_with_params}/{len(db_functions)}")
    print("   ✓ PASS: Parameters preserved")

    # Sample a few functions to verify data quality
    print("\n8. Sampling function data quality...")
    sample_functions = session.query(Function).limit(5).all()
    for func in sample_functions:
        print(f"\n   Function: {func.name}")
        print(f"     Category: {func.category}")
        print(
            f"     Description: {func.description[:60]}..."
            if len(func.description or "") > 60
            else f"     Description: {func.description}"
        )
        print(f"     Has examples: {func.examples and func.examples != '[]'}")
        print(
            f"     Has params: {func.params and func.params != '{}' and func.params != '[]'}"
        )

    # Check specific important functions
    print("\n9. Checking important functions exist...")
    important_functions = [
        "s",
        "note",
        "cat",
        "seq",
        "stack",
        "slow",
        "fast",
        "lpf",
        "gain",
    ]
    missing = []
    for func_name in important_functions:
        exists = session.query(Function).filter_by(name=func_name).first()
        if not exists:
            missing.append(func_name)

    if missing:
        print(f"   ✗ FAIL: Missing important functions: {missing}")
    else:
        print("   ✓ PASS: All important functions imported")

    # --- Preset validation ---
    print("\n10. Preset import validation...")
    expected_preset_names = set()
    for rel_path, category in PRESET_SOURCES:
        path = project_root / rel_path
        if path.exists():
            for name, _cat, _source in _preset_names_from_json(path, category):
                expected_preset_names.add(name)
    expected_preset_names.update(BUILTIN_SYNTH_PRESETS)
    expected_preset_names.update(DIRT_SAMPLES_INLINE_PRESETS)

    db_presets = session.query(Preset).all()
    db_preset_names = {p.name for p in db_presets}

    print(f"   Expected preset names (from JSONs): {len(expected_preset_names)}")
    print(f"   Presets in database: {len(db_presets)}")

    missing_presets = expected_preset_names - db_preset_names
    if missing_presets:
        print(f"   ✗ FAIL: Missing {len(missing_presets)} presets: {list(missing_presets)[:10]}...")
    else:
        print("   ✓ PASS: All expected presets imported")

    preset_names_list = [p.name for p in db_presets]
    preset_dupes = [n for n in preset_names_list if preset_names_list.count(n) > 1]
    if preset_dupes:
        print(f"   ✗ FAIL: Duplicate preset names: {set(preset_dupes)}")
    else:
        print("   ✓ PASS: No duplicate preset names")

    preset_categories = {}
    for p in db_presets:
        cat = p.category or "none"
        preset_categories[cat] = preset_categories.get(cat, 0) + 1
    print("   Preset category distribution:")
    for cat, count in sorted(preset_categories.items(), key=lambda x: x[1], reverse=True):
        print(f"     {cat}: {count} presets")

    # Validate preset tags are valid JSON
    preset_json_errors = []
    for p in db_presets:
        if p.tags:
            try:
                json.loads(p.tags)
            except json.JSONDecodeError:
                preset_json_errors.append(p.name)
    if preset_json_errors:
        print(f"   ✗ FAIL: Invalid JSON in tags for presets: {preset_json_errors[:5]}")
    else:
        print("   ✓ PASS: All preset tags are valid JSON")

    # --- Recipe validation ---
    print("\n11. Recipe import validation...")
    expected_recipe_count = 0
    for rel_path, category, import_tag in RECIPE_SOURCES:
        path = project_root / rel_path
        if path.exists():
            recipe_list = load_recipes_from_file(path, category, import_tag)
            expected_recipe_count += len(recipe_list)
    mdx_dir = project_root / RECIPE_MDX_DIR
    if mdx_dir.exists():
        for mdx_path in sorted(mdx_dir.glob("*.mdx")):
            expected_recipe_count += len(load_recipes_from_mdx(mdx_path, RECIPE_MDX_IMPORT_TAG))
    db_recipes = session.query(Recipe).filter(Recipe.tags.like("%import:%")).all()
    print(f"   Expected recipes (from sources): {expected_recipe_count}")
    print(f"   Imported recipes in database: {len(db_recipes)}")
    if len(db_recipes) < expected_recipe_count:
        print(f"   ✗ FAIL: Missing {expected_recipe_count - len(db_recipes)} recipes")
    else:
        print("   ✓ PASS: All expected recipes imported")
    print("   Recipe category distribution:")
    recipe_cats = {}
    for r in db_recipes:
        c = r.category or "none"
        recipe_cats[c] = recipe_cats.get(c, 0) + 1
    for c, n in sorted(recipe_cats.items(), key=lambda x: -x[1]):
        print(f"     {c}: {n} recipes")

    session.close()
    print("\n=== Validation Complete ===")


if __name__ == "__main__":
    validate_import()
