#!/usr/bin/env python3
"""
Import Strudel functions from doc.json into the knowledge base database.

This script:
1. Loads functions from doc.json
2. Categorizes and cleans the data
3. Imports into the SQLite database
"""

import json
import re
from html import unescape
from pathlib import Path

from database import Function, get_session

# Pattern constructors (from pattern.mjs, but constructors, not time modifiers)
PATTERN_CONSTRUCTORS = {
    "cat",
    "seq",
    "stack",
    "stepcat",
    "arrange",
    "silence",
    "run",
    "binary",
    "binaryN",
    "polymeter",
    "polymeterSteps",
}

# Time modifiers (from pattern.mjs)
TIME_MODIFIERS = {
    "slow",
    "fast",
    "early",
    "late",
    "rev",
    "iter",
    "iterBack",
    "euclid",
    "euclidRot",
    "euclidLegato",
    "palindrome",
    "ply",
    "segment",
    "compress",
    "zoom",
    "linger",
    "fastGap",
    "inside",
    "outside",
    "cpm",
    "ribbon",
    "swing",
    "swingBy",
    "clip",
    "legato",
}


def get_category(func_name, meta_filename):
    """Determine function category based on name and source file."""
    if meta_filename == "pattern.mjs":
        if func_name in PATTERN_CONSTRUCTORS:
            return "pattern"
        elif func_name in TIME_MODIFIERS:
            return "time"
        else:
            return "pattern"  # Default for pattern.mjs
    elif meta_filename == "controls.mjs":
        return "control"
    elif meta_filename == "signal.mjs":
        return "signal"
    elif meta_filename in ["dough.mjs", "superdough.mjs"]:
        return "effect"
    elif meta_filename == "motion.mjs":
        return "motion"
    elif meta_filename in ["util.mjs", "repl.mjs", "pick.mjs"]:
        return "utility"
    else:
        return "other"


def strip_html(html_text):
    """Remove HTML tags but preserve text content."""
    if not html_text:
        return ""
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", html_text)
    # Decode HTML entities
    text = unescape(text)
    return text.strip()


def validate_json_array(data):
    """Ensure data is a valid JSON array string."""
    if not data:
        return "[]"
    if isinstance(data, list):
        return json.dumps(data)
    if isinstance(data, str):
        try:
            # Try to parse and re-stringify to validate
            parsed = json.loads(data)
            return json.dumps(parsed)
        except json.JSONDecodeError:
            return "[]"
    return "[]"


def validate_json_object(data):
    """Ensure data is a valid JSON object string."""
    if not data:
        return "{}"
    if isinstance(data, dict):
        return json.dumps(data)
    if isinstance(data, list):
        return json.dumps(data)
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            return json.dumps(parsed)
        except json.JSONDecodeError:
            return "{}"
    return "{}"


def should_import_function(func):
    """Check if function should be imported."""
    name = func.get("name", "")
    kind = func.get("kind", "")

    # Filter out private functions and packages
    if not name or name.startswith("_") or kind == "package":
        return False
    return True


def import_functions(doc_json_path, db_session):
    """Import functions from doc.json into database."""
    with open(doc_json_path, "r") as f:
        data = json.load(f)

    functions = data.get("docs", [])
    imported = 0
    skipped = 0
    errors = []

    # Track names we've processed in this batch to avoid duplicates
    processed_names = set()
    # Pre-load all existing functions into a dict for faster lookup
    existing_functions = {f.name: f for f in db_session.query(Function).all()}

    for func in functions:
        if not should_import_function(func):
            skipped += 1
            continue

        try:
            name = func["name"]

            # Skip if we've already processed this name in this batch
            if name in processed_names:
                skipped += 1
                continue

            processed_names.add(name)

            meta = func.get("meta", {})
            filename = meta.get("filename", "unknown")

            # Check if function already exists in database
            if name in existing_functions:
                # Update existing
                func_obj = existing_functions[name]
            else:
                # Create new
                func_obj = Function()
                db_session.add(func_obj)
                existing_functions[name] = func_obj  # Track it

            # Set basic fields
            func_obj.name = name
            func_obj.longname = func.get("longname", name)
            func_obj.description = strip_html(func.get("description", ""))
            func_obj.category = get_category(name, filename)
            func_obj.kind = func.get("kind", "")
            func_obj.scope = func.get("scope", "")

            # Set JSON fields
            func_obj.synonyms = validate_json_array(func.get("synonyms", []))
            func_obj.examples = validate_json_array(func.get("examples", []))
            func_obj.params = validate_json_object(func.get("params", []))

            imported += 1

        except Exception as e:
            errors.append(f"Error importing {func.get('name', 'unknown')}: {str(e)}")
            skipped += 1

    db_session.commit()

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
    }


def main():
    """Main import function."""
    # Find doc.json (should be in project root)
    project_root = Path(__file__).parent.parent
    doc_json_path = project_root / "doc.json"

    if not doc_json_path.exists():
        print(f"Error: doc.json not found at {doc_json_path}")
        return

    print(f"Loading functions from {doc_json_path}...")

    session = get_session()

    try:
        result = import_functions(doc_json_path, session)

        print("\n=== Import Summary ===")
        print(f"Imported: {result['imported']} functions")
        print(f"Skipped: {result['skipped']} functions")

        if result["errors"]:
            print(f"\nErrors ({len(result['errors'])}):")
            for error in result["errors"][:10]:  # Show first 10 errors
                print(f"  - {error}")
            if len(result["errors"]) > 10:
                print(f"  ... and {len(result['errors']) - 10} more errors")

        print("\nImport completed!")

    except Exception as e:
        print(f"Fatal error: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
