#!/usr/bin/env python3
"""
Import Strudel functions, presets, and recipes into the knowledge base database.

This script:
1. Loads functions from doc.json and imports into the functions table
2. Loads presets from sample-bank JSONs and built-in lists into the presets table
3. Loads recipes (tunes, examples) from website and examples JS/MJS files into the recipes table
"""

import json
import re
from html import unescape
from pathlib import Path

from database import Function, Preset, Recipe, get_session


# ---------------------------------------------------------------------------
# Recipe sources: (path relative to project root, category, import_tag)
# import_tag is used in Recipe.tags so we can replace these on re-import
RECIPE_SOURCES = [
    ("website/src/examples.mjs", "tune", "import:website-examples"),
    ("website/src/repl/tunes.mjs", "tune", "import:website-tunes"),
    ("examples/codemirror-repl/tunes.mjs", "tune", "import:examples-codemirror"),
    ("examples/minimal-repl/tune.mjs", "tune", "import:examples-minimal"),
]
# MDX recipe pages: we glob for *.mdx and extract MiniRepl tune= snippets
RECIPE_MDX_DIR = "website/src/pages/recipes"
RECIPE_MDX_IMPORT_TAG = "import:recipes-mdx"

# Sample-bank JSONs under website/public/ : (path relative to project root, category)
PRESET_SOURCES = [
    ("website/public/tidal-drum-machines.json", "drum-machines"),
    ("website/public/uzu-drumkit.json", "drum-machines"),
    ("website/public/uzu-wavetables.json", "wavetables"),
    ("website/public/vcsl.json", "percussion"),
    ("website/public/mridangam.json", "drum-machines"),
    ("website/public/piano.json", "instruments"),
]

# Built-in synths/sounds registered by registerSynthSounds() and registerZZFXSounds()
# (packages/superdough/synth.mjs, zzfx.mjs) — not in any JSON
BUILTIN_SYNTH_PRESETS = [
    "triangle", "square", "sawtooth", "sine", "user",  # waveforms
    "sbd", "supersaw", "bytebeat", "pulse",  # synths
    "pink", "white", "brown", "crackle",  # noises
    "zzfx", "z_sine", "z_sawtooth", "z_triangle", "z_square", "z_tan", "z_noise",  # ZZFX
]

# Inline Dirt-Samples bank in website prebake (no separate JSON in repo)
DIRT_SAMPLES_INLINE_PRESETS = [
    "casio", "crow", "insect", "wind", "jazz", "metal", "east", "space", "numbers", "num",
]

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


# ---------------------------------------------------------------------------
# Recipe extraction from JS/MJS files
def _title_from_first_comment(code):
    """Extract a short title from the first comment line (// ... or // "..." @by ...)."""
    first = code.lstrip().split("\n")[0].strip()
    if first.startswith("//"):
        rest = first[2:].strip()
        # "title" @by author or "title" or plain text
        m = re.match(r'"([^"]+)"', rest)
        if m:
            return m.group(1).strip()
        if rest:
            return rest.split("@by")[0].strip()[:80]
    return None


def _slug_from_name(name):
    """Turn export name (e.g. giantSteps) into a readable slug."""
    return re.sub(r"([A-Z])", r" \1", name).strip().lower().replace(" ", "-")[:60]


def _extract_examples_array(content):
    """Extract template literal items from export const examples = [ `...`, `...` ];"""
    out = []
    # Each element is `content` followed by comma or ]; (comma often right after backtick)
    pattern = re.compile(r"`([\s\S]*?)`\s*,?\s*\n", re.MULTILINE)
    for m in pattern.finditer(content):
        code = m.group(1).strip()
        if not code or len(code) < 10:
            continue
        title = _title_from_first_comment(code) or "Untitled example"
        out.append({"title": title, "description": None, "code": code})
    return out


def _extract_tunes_exports(content):
    """Extract named exports: export const name = `...`; Content may contain escaped backticks."""
    out = []
    pos = 0
    while True:
        # Find next "export const NAME = `" (optional newline after backtick)
        m = re.search(r"export\s+const\s+(\w+)\s*=\s*`\n?", content[pos:])
        if not m:
            break
        name = m.group(1)
        start = pos + m.end()
        # Find closing: (1) newline then optional space then backtick, or (2) backtick then optional ; then newline
        end = start
        i = start
        while i < len(content):
            if content[i] == "\\" and i + 1 < len(content):
                i += 2
                continue
            if content[i] == "\n":
                j = i + 1
                while j < len(content) and content[j] in " \t":
                    j += 1
                if j < len(content) and content[j] == "\\" and j + 1 < len(content):
                    i = j + 2
                    continue
                if j < len(content) and content[j] == "`":
                    end = i
                    break
            if content[i] == "`":
                # Closing at end of line: ` then optional ; then optional space then newline
                j = i + 1
                while j < len(content) and content[j] in " \t;":
                    j += 1
                if j < len(content) and content[j] == "\n":
                    end = i
                    break
            i += 1
        else:
            break
        code = content[start:end].strip()
        if code and len(code) >= 10:
            title = _title_from_first_comment(code) or _slug_from_name(name)
            out.append({"title": title, "description": None, "code": code, "key": name})
        pos = end + 1
        # Skip past the closing backtick and optional newline to avoid re-matching
        while pos < len(content) and content[pos] in " `\t\n":
            pos += 1
    return out


def _extract_default_tune(content):
    """Extract single default export: export default `...`;"""
    m = re.search(r"export\s+default\s*`\n([\s\S]*?)\n\s*`", content)
    if not m:
        return []
    code = m.group(1).strip()
    if not code or len(code) < 10:
        return []
    title = _title_from_first_comment(code) or "Minimal REPL tune"
    return [{"title": title, "description": None, "code": code}]


def _description_from_tune_code(code):
    """Build a short description from the first comment line(s) of tune code."""
    lines = code.strip().split("\n")
    comment_lines = []
    for line in lines:
        s = line.strip()
        if s.startswith("//"):
            comment_lines.append(s[2:].strip())
        elif s and not comment_lines:
            break
        elif not s and comment_lines:
            continue
        else:
            break
    if not comment_lines:
        return ""
    first = comment_lines[0]
    if first.startswith('"') and '"' in first[1:]:
        first = first[1 : first.index('"', 1)]
    first = first.split("@by")[0].strip()
    return first[:500] if first else ""


def _infer_difficulty(code):
    """Infer difficulty from code length and complexity heuristics."""
    code_len = len(code)
    advanced_patterns = [
        r"\.layer\s*\(",
        r"\.superimpose\s*\(",
        r"\.jux\b",
        r"\.juxBy\b",
        r"\.struct\s*\(",
        r"\.euclid\b",
        r"\.euclidRot\b",
        r"\.segment\s*\(",
        r"\.chunk\s*\(",
        r"\.mask\s*\(",
        r"\.when\s*\(",
        r"\.rarely\s*\(",
        r"\.sometimes\s*\(",
        r"x=>x\.",
        r"\.add\s*\(\s*note",
    ]
    intermediate_patterns = [
        r"\.scale\s*\(",
        r"\.chord\s*\(",
        r"\.voicing\s*\(",
        r"\.stack\s*\(",
        r"\.seq\s*\(",
        r"\.chop\s*\(",
        r"\.slice\s*\(",
        r"\.delay\s*\(",
        r"\.lpf\s*\(",
        r"\.lpenv\s*\(",
        r"\.room\s*\(",
    ]
    for pat in advanced_patterns:
        if re.search(pat, code):
            return "advanced"
    for pat in intermediate_patterns:
        if re.search(pat, code):
            return "intermediate"
    if code_len > 800:
        return "intermediate"
    return "beginner"


def _extract_function_names_from_code(code):
    """Extract likely Strudel function/method names from code (e.g. s(, .note(, scale()."""
    # Match: .name( or word name( at line start or after space
    names = set()
    for m in re.finditer(r"(?:^|[^\w])(\w+)\s*\(", code):
        name = m.group(1)
        if len(name) >= 2 and not name.startswith("_") and name not in ("if", "for", "while", "function", "return", "const", "let", "var"):
            names.add(name)
    return list(names)


def _extract_recipes_from_mdx(content, page_title, source_name):
    """
    Extract recipe snippets from MDX: <MiniRepl tune={`...`} ... />.
    Uses the last ## heading before each tune as section; captures preceding prose as description.
    """
    page_title = page_title or "Recipes"
    section_positions = [(m.start(), m.group(1).strip()) for m in re.finditer(r"^##\s+(.+)$", content, re.MULTILINE)]
    tune_pattern = re.compile(r"tune=\{\s*`([\s\S]*?)`\s*\}")
    out = []
    for i, m in enumerate(tune_pattern.finditer(content)):
        code = m.group(1).strip()
        if not code or len(code) < 3:
            continue
        start = m.start()
        section = "Recipe"
        for pos, heading in section_positions:
            if pos < start:
                section = heading
        # Preceding prose: from last /> (previous snippet) to this <MiniRepl; use last paragraph only
        block_start = content.rfind("/>", 0, start)
        if block_start != -1:
            block_start += 2
        else:
            block_start = 0
            for pos, _ in section_positions:
                if pos < start:
                    block_start = pos
        prose = content[block_start:start]
        paragraphs = [p.strip() for p in prose.split("\n\n") if p.strip()]
        last_para = ""
        for p in reversed(paragraphs):
            if p.startswith("<"):
                continue
            last_para = re.sub(r"<[^>]+>", " ", p)
            last_para = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", last_para)
            last_para = re.sub(r"\s+", " ", last_para).strip()
            if len(last_para) > 20:
                break
        description = last_para[:300] if last_para else f"Demonstrates: {section}."
        title = f"{page_title} – {section}"
        if len(section_positions) <= 1 and i > 0:
            title = f"{page_title} – {section} ({i + 1})"
        out.append({
            "title": title[:200],
            "description": description[:1000],
            "code": code,
            "category": "recipe",
            "section": section,
            "source": source_name,
        })
    return out


def load_recipes_from_mdx(file_path, import_tag):
    """Load recipe dicts from an MDX file (MiniRepl tune= snippets)."""
    if not file_path.exists():
        return []
    text = file_path.read_text(encoding="utf-8", errors="replace")
    page_title = "Recipes"
    m = re.search(r"^title:\s*[\"']?([^\"'\n]+)[\"']?", text, re.MULTILINE)
    if m:
        page_title = m.group(1).strip()
    recipes = _extract_recipes_from_mdx(text, page_title, file_path.name)
    for r in recipes:
        r["tags"] = json.dumps([import_tag, "recipe", r.get("section", ""), r.get("source", "")])
    return recipes


def _enrich_recipe(recipe_dict, function_name_to_id):
    """Fill in description, difficulty, and related_functions from code when missing."""
    code = recipe_dict.get("code") or ""
    if not code:
        return
    if not (recipe_dict.get("description") or "").strip():
        if recipe_dict.get("category") == "tune":
            recipe_dict["description"] = _description_from_tune_code(code) or (
                "Strudel tune. " + (recipe_dict.get("title") or "Pattern")[:80]
            )
        else:
            section = recipe_dict.get("section", "")
            recipe_dict["description"] = f"Demonstrates: {section}."
    recipe_dict["difficulty"] = _infer_difficulty(code)
    names = _extract_function_names_from_code(code)
    ids = [function_name_to_id[n] for n in names if n in function_name_to_id]
    recipe_dict["related_functions"] = json.dumps(ids) if ids else "[]"


def load_recipes_from_file(file_path, category, import_tag):
    """
    Load recipe dicts from a JS/MJS file. Returns list of dicts with title, description, code, category, tags.
    """
    if not file_path.exists():
        return []
    text = file_path.read_text(encoding="utf-8", errors="replace")
    recipes = []
    if "export const examples = [" in text:
        for r in _extract_examples_array(text):
            r["category"] = category
            r["tags"] = json.dumps([import_tag, "tune", "example"])
            recipes.append(r)
    elif "export default `" in text and "export const " not in text.replace("export default `", "", 1):
        for r in _extract_default_tune(text):
            r["category"] = category
            r["tags"] = json.dumps([import_tag, "tune"])
            recipes.append(r)
    else:
        for r in _extract_tunes_exports(text):
            r["category"] = category
            r["tags"] = json.dumps([import_tag, "tune", r.get("key", "")])
            recipes.append(r)
    return recipes


def import_recipes(project_root, db_session):
    """Import recipes from RECIPE_SOURCES into the recipes table. Replaces previously imported recipes."""
    db_session.query(Recipe).filter(Recipe.tags.like("%import:%")).delete(synchronize_session=False)
    db_session.commit()

    function_name_to_id = {f.name: f.id for f in db_session.query(Function).all()}
    imported = 0
    skipped = 0
    errors = []

    def add_recipe(r, rel_path_for_error):
        nonlocal imported, skipped
        code = (r.get("code") or "").strip()
        if not code:
            skipped += 1
            return
        _enrich_recipe(r, function_name_to_id)
        title = (r.get("title") or "Untitled")[:200]
        rec = Recipe(
            title=title,
            description=(r.get("description") or "").strip()[:2000],
            code=code,
            category=r.get("category") or "tune",
            difficulty=r.get("difficulty"),
            tags=r.get("tags") or "[]",
            related_functions=r.get("related_functions", "[]"),
        )
        db_session.add(rec)
        imported += 1

    for rel_path, category, import_tag in RECIPE_SOURCES:
        path = project_root / rel_path
        try:
            recipe_list = load_recipes_from_file(path, category, import_tag)
            for r in recipe_list:
                try:
                    add_recipe(r, rel_path)
                except Exception as e:
                    errors.append(f"{rel_path}: {e}")
        except Exception as e:
            errors.append(f"Error loading {rel_path}: {e}")

    mdx_dir = project_root / RECIPE_MDX_DIR
    if mdx_dir.exists():
        for mdx_path in sorted(mdx_dir.glob("*.mdx")):
            try:
                recipe_list = load_recipes_from_mdx(mdx_path, RECIPE_MDX_IMPORT_TAG)
                for r in recipe_list:
                    try:
                        add_recipe(r, mdx_path.name)
                    except Exception as e:
                        errors.append(f"{mdx_path.name}: {e}")
            except Exception as e:
                errors.append(f"Error loading {mdx_path}: {e}")

    db_session.commit()
    return {"imported": imported, "skipped": skipped, "errors": errors}


def _preset_names_from_json(file_path, category):
    """
    Extract preset names from a sample-bank JSON.
    Returns list of (name, category, source_filename).
    Skips _base. Handles flat keys (value is list) and nested banks (value is dict).
    """
    with open(file_path, "r") as f:
        data = json.load(f)
    source_name = file_path.name
    out = []
    for key, value in data.items():
        if key == "_base":
            continue
        if not key or not isinstance(key, str):
            continue
        # Flat: key is preset name, value is list of sample paths
        if isinstance(value, list):
            out.append((key, category, source_name))
        # Nested bank: key is bank name (e.g. "piano"), value is dict of note->file
        elif isinstance(value, dict):
            out.append((key, category, source_name))
    return out


def import_presets(project_root, db_session):
    """Import presets from sample-bank JSONs into the presets table."""
    existing_by_name = {p.name: p for p in db_session.query(Preset).all()}
    processed_names = set()
    imported = 0
    skipped = 0
    errors = []

    for rel_path, category in PRESET_SOURCES:
        path = project_root / rel_path
        if not path.exists():
            continue
        try:
            for name, cat, source_name in _preset_names_from_json(path, category):
                if name in processed_names:
                    skipped += 1
                    continue
                processed_names.add(name)
                tags = json.dumps([source_name, category])
                code_example = f's("{name}")'
                description = f"Sample preset: {name} (from {source_name}). Use with s(\"{name}\")."
                if name in existing_by_name:
                    p = existing_by_name[name]
                else:
                    p = Preset()
                    db_session.add(p)
                    existing_by_name[name] = p
                p.name = name
                p.type = "sound"
                p.category = cat
                p.description = description
                p.code_example = code_example
                p.tags = tags
                imported += 1
        except Exception as e:
            errors.append(f"Error loading {rel_path}: {e}")

    # Built-in synths (no JSON file; registered in code)
    for name in BUILTIN_SYNTH_PRESETS:
        if name in processed_names:
            skipped += 1
            continue
        processed_names.add(name)
        tags = json.dumps(["builtin", "synth"])
        if name in existing_by_name:
            p = existing_by_name[name]
        else:
            p = Preset()
            db_session.add(p)
            existing_by_name[name] = p
        p.name = name
        p.type = "synth"
        p.category = "synth"
        p.description = f"Built-in synth/sound: {name}. Use with s(\"{name}\")."
        p.code_example = f's("{name}")'
        p.tags = tags
        imported += 1

    # Inline Dirt-Samples bank from website prebake (no separate JSON)
    for name in DIRT_SAMPLES_INLINE_PRESETS:
        if name in processed_names:
            skipped += 1
            continue
        processed_names.add(name)
        tags = json.dumps(["dirt-samples", "samples"])
        if name in existing_by_name:
            p = existing_by_name[name]
        else:
            p = Preset()
            db_session.add(p)
            existing_by_name[name] = p
        p.name = name
        p.type = "sound"
        p.category = "samples"
        p.description = f"Dirt-Samples bank: {name}. Use with s(\"{name}\")."
        p.code_example = f's("{name}")'
        p.tags = tags
        imported += 1

    db_session.commit()
    return {"imported": imported, "skipped": skipped, "errors": errors}


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
        result_f = import_functions(doc_json_path, session)
        result_p = import_presets(project_root, session)
        result_r = import_recipes(project_root, session)

        print("\n=== Import Summary ===")
        print("Functions:")
        print(f"  Imported: {result_f['imported']}")
        print(f"  Skipped: {result_f['skipped']}")
        if result_f["errors"]:
            print(f"  Errors: {len(result_f['errors'])}")
        print("Presets:")
        print(f"  Imported: {result_p['imported']}")
        print(f"  Skipped: {result_p['skipped']}")
        if result_p["errors"]:
            print(f"  Errors: {len(result_p['errors'])}")
        print("Recipes:")
        print(f"  Imported: {result_r['imported']}")
        print(f"  Skipped: {result_r['skipped']}")
        if result_r["errors"]:
            print(f"  Errors: {len(result_r['errors'])}")

        if result_f["errors"]:
            print("\nFunction errors:")
            for error in result_f["errors"][:10]:
                print(f"  - {error}")
            if len(result_f["errors"]) > 10:
                print(f"  ... and {len(result_f['errors']) - 10} more")
        if result_p["errors"]:
            print("\nPreset errors:")
            for error in result_p["errors"][:10]:
                print(f"  - {error}")
            if len(result_p["errors"]) > 10:
                print(f"  ... and {len(result_p['errors']) - 10} more")
        if result_r["errors"]:
            print("\nRecipe errors:")
            for error in result_r["errors"][:10]:
                print(f"  - {error}")
            if len(result_r["errors"]) > 10:
                print(f"  ... and {len(result_r['errors']) - 10} more")

        print("\nImport completed!")

    except Exception as e:
        print(f"Fatal error: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
