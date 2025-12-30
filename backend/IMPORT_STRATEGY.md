# Data Import Strategy

## Overview
This document outlines how we'll import and organize data from `doc.json` into the SQLite knowledge base.

## Data Source Analysis

### doc.json Structure
- **Total docs**: 567 entries
- **Functions with names**: 547 (excludes private functions starting with `_`)
- **Key fields** (present in 100% of functions):
  - `name`: Function name
  - `longname`: Full qualified name
  - `kind`: Type (member, function, etc.)
  - `scope`: global, instance, etc.
  - `description`: HTML description
  - `meta`: File location info
- **Optional fields**:
  - `params`: 96% have this
  - `examples`: 74% have this
  - `synonyms`: 60% have this

### Main Source Files
- `controls.mjs`: 199 functions (sound, note, effects, parameters)
- `pattern.mjs`: 156 functions (pattern constructors, time modifiers)
- `signal.mjs`: 62 functions (oscillators, signals)
- `dough.mjs`: 44 functions (audio effects)
- Others: motion, pick, euclid, etc.

## Categorization Strategy

### Function Categories (based on filename and usage)

1. **pattern** - Pattern constructors
   - Files: `pattern.mjs` (constructors: cat, seq, stack, stepcat, etc.)
   - Examples: `cat`, `seq`, `stack`, `stepcat`, `arrange`, `silence`

2. **time** - Time modifiers
   - Files: `pattern.mjs` (time functions)
   - Examples: `slow`, `fast`, `early`, `late`, `rev`, `iter`, `euclid`

3. **control** - Parameter/control functions
   - Files: `controls.mjs` (most functions)
   - Examples: `s`, `note`, `n`, `gain`, `cutoff`, `pan`

4. **effect** - Audio effects
   - Files: `dough.mjs`, `superdough.mjs`
   - Examples: `lpf`, `hpf`, `distort`, `reverb`, `delay`

5. **signal** - Signal generators
   - Files: `signal.mjs`
   - Examples: `sine`, `saw`, `square`, `noise`

6. **utility** - Utility functions
   - Files: `util.mjs`, `repl.mjs`, `pick.mjs`
   - Examples: `setcpm`, `pick`, `getFreq`

7. **motion** - Motion/device input
   - Files: `motion.mjs`
   - Examples: `accelerationX`, `gravityX`

8. **other** - Everything else
   - Files: `euclid.mjs`, `voicings.mjs`, etc.

## Data Mapping

### doc.json → functions table

| doc.json field | database field | Transformation |
|---------------|----------------|----------------|
| `name` | `name` | Direct (must exist) |
| `longname` | `longname` | Direct |
| `description` | `description` | Strip HTML tags, keep text |
| `meta.filename` | → `category` | Map filename to category |
| `kind` | `kind` | Direct |
| `scope` | `scope` | Direct |
| `synonyms` | `synonyms` | JSON array → JSON string |
| `examples` | `examples` | JSON array → JSON string |
| `params` | `params` | JSON object → JSON string |

### Category Mapping Logic

```python
def get_category(meta_filename):
    mapping = {
        'pattern.mjs': 'pattern',  # Will need to distinguish constructors vs time modifiers
        'controls.mjs': 'control',
        'signal.mjs': 'signal',
        'dough.mjs': 'effect',
        'superdough.mjs': 'effect',
        'motion.mjs': 'motion',
        'util.mjs': 'utility',
        'repl.mjs': 'utility',
        'pick.mjs': 'utility',
        'euclid.mjs': 'time',  # Time-related
        'voicings.mjs': 'control',  # Note-related
    }
    return mapping.get(meta_filename, 'other')
```

### Special Cases

1. **Pattern.mjs functions**: Need to distinguish:
   - Pattern constructors (cat, seq, stack) → category: 'pattern'
   - Time modifiers (slow, fast, rev) → category: 'time'
   - Solution: Check function name against known lists

2. **HTML in descriptions**: Strip HTML but preserve structure
   - Use `html.parser` or regex to clean
   - Keep important info (code examples, links)

3. **Missing fields**: Handle gracefully
   - `params`: Use empty JSON array `[]`
   - `examples`: Use empty JSON array `[]`
   - `synonyms`: Use empty JSON array `[]`

## Data Cleaning Rules

1. **Filter out**:
   - Functions starting with `_` (private)
   - Functions without `name`
   - Functions with `kind: 'package'`

2. **Normalize**:
   - Strip HTML from descriptions
   - Ensure JSON arrays are valid JSON
   - Trim whitespace from strings

3. **Validate**:
   - Check required fields exist
   - Verify JSON is valid before storing
   - Ensure unique function names

## Import Process

1. **Load doc.json**
2. **Filter valid functions**
3. **Categorize each function**
4. **Clean and transform data**
5. **Insert into database** (batch insert for performance)
6. **Report statistics** (imported, skipped, errors)

## Validation Checklist

After import, verify:
- [ ] All functions from doc.json are imported (except filtered ones)
- [ ] Categories are correctly assigned
- [ ] JSON fields are valid JSON
- [ ] No duplicate function names
- [ ] Examples are preserved
- [ ] Synonyms are preserved
- [ ] Parameters are preserved

## Next Steps After Import

1. Import presets (sound banks, drum kits)
2. Import recipes (from MDX files)
3. Create function relationships (based on usage patterns)

