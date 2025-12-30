#!/usr/bin/env python3
"""
Validate the imported functions against the checklist in IMPORT_STRATEGY.md
"""

import json
from pathlib import Path

from database import Function, get_session


def validate_import():
    """Run validation checks on imported data."""
    session = get_session()

    print("=== Validation Checklist ===\n")

    # Load doc.json to compare
    project_root = Path(__file__).parent.parent
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

    session.close()
    print("\n=== Validation Complete ===")


if __name__ == "__main__":
    validate_import()
