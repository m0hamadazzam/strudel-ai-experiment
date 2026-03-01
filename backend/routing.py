"""
Deterministic routing heuristics for the copilot request pipeline.

Decides:
  - whether to prefetch KB context before the LLM call
  - whether to enable web search in the LLM call

No LLM is used here — only regex and set lookups.
"""

from __future__ import annotations

import re

_CODE_PATTERN = re.compile(r"""[.()\[\]{}"']|=>|function\s""")
_API_QUESTION = re.compile(
    r"\b(how\s+to|what\s+does|what\s+is|error|fails?|syntax|bug)\b", re.I
)
_DOCS_REQUEST = re.compile(
    r"\b(docs?|documentation|latest|link|according\s+to)\b", re.I
)

EFFECT_ALIASES: dict[str, str] = {
    "low pass filter": "lpf",
    "lowpass": "lpf",
    "low pass": "lpf",
    "high pass filter": "hpf",
    "highpass": "hpf",
    "high pass": "hpf",
    "band pass filter": "bpf",
    "bandpass": "bpf",
    "band pass": "bpf",
    "reverb": "room",
    "distortion": "distort",
    "volume": "gain",
    "loudness": "gain",
    "panning": "pan",
    "bit crush": "crush",
    "bitcrush": "crush",
}

# ---------------------------------------------------------------------------
# Sound / instrument detection
# ---------------------------------------------------------------------------

SOUND_ALIASES: dict[str, list[str]] = {
    "kick": ["bd"],
    "bass drum": ["bd"],
    "bassdrum": ["bd"],
    "snare": ["sd"],
    "snare drum": ["sd"],
    "hi-hat": ["hh"],
    "hihat": ["hh"],
    "hi hat": ["hh"],
    "hat": ["hh"],
    "closed hat": ["hh"],
    "open hat": ["oh"],
    "open hi-hat": ["oh"],
    "open hihat": ["oh"],
    "clap": ["cp"],
    "handclap": ["cp"],
    "rimshot": ["rim"],
    "tom": ["lt", "mt", "ht"],
    "low tom": ["lt"],
    "mid tom": ["mt"],
    "high tom": ["ht"],
    "crash": ["cr"],
    "crash cymbal": ["cr"],
    "ride": ["rd"],
    "ride cymbal": ["rd"],
    "cowbell": ["cb"],
    "shaker": ["sh"],
    "tambourine": ["tb"],
}

_DRUM_KIT_BASICS = ["bd", "sd", "hh", "oh", "cp", "rim"]

_MUSIC_CREATION_RE = re.compile(
    r"\b(beat|rhythm|drums?|percussion|groove|loop|drum\s*pattern|drum\s*beat)\b",
    re.I,
)
_SYNTH_REQUEST_RE = re.compile(
    r"\b(melody|bass|bassline|lead|pad|synth|chord|arpeggio|piano)\b", re.I
)


def detect_sound_types(query: str) -> tuple[list[str], bool]:
    """Detect which sound preset categories the query needs.

    Returns:
        (drum_suffixes, needs_synth)
        drum_suffixes: e.g. ["bd", "sd", "hh"] — used to fetch matching presets.
        needs_synth: True when synth/melodic presets should be included.
    """
    lower = query.lower()
    suffixes: list[str] = []
    seen: set[str] = set()

    for alias, types in SOUND_ALIASES.items():
        if alias in lower:
            for t in types:
                if t not in seen:
                    seen.add(t)
                    suffixes.append(t)

    if _MUSIC_CREATION_RE.search(query):
        for t in _DRUM_KIT_BASICS:
            if t not in seen:
                seen.add(t)
                suffixes.append(t)

    needs_synth = bool(_SYNTH_REQUEST_RE.search(query))
    return suffixes, needs_synth


def should_prefetch_kb(user_msg: str, known_fn_names: set[str]) -> bool:
    """Return True when the user is asking about specific Strudel API.

    Triggers on:
    - code-ish tokens (parens, brackets, arrow functions)
    - API/help questions ("how to", "error", "syntax")
    - known function names mentioned by the user
    - natural-language effect names (alias map)

    Does NOT trigger on creative/genre keywords ("techno", "ambient").
    """
    if _CODE_PATTERN.search(user_msg):
        return True
    if _API_QUESTION.search(user_msg):
        return True

    msg_lower = user_msg.lower()

    tokens = set(re.findall(r"\b\w+\b", msg_lower))
    if tokens & known_fn_names:
        return True

    if any(alias in msg_lower for alias in EFFECT_ALIASES):
        return True

    if any(alias in msg_lower for alias in SOUND_ALIASES):
        return True

    return False


def should_enable_web_search(user_msg: str, kb_prefetch_context: str | None) -> bool:
    """Return True when web search should be attached to the LLM call.

    Triggers on:
    - explicit docs/link requests
    - KB prefetch was attempted but returned very little
    """
    if _DOCS_REQUEST.search(user_msg):
        return True
    if kb_prefetch_context is not None and len(kb_prefetch_context.strip()) < 50:
        return True
    return False


def expand_query_with_aliases(query: str) -> str:
    """If the query contains a known effect alias, append the canonical
    Strudel function name so retrieval picks up the right docs."""
    lower = query.lower()
    expansions: list[str] = []
    for alias, canonical in EFFECT_ALIASES.items():
        if alias in lower and canonical not in lower:
            expansions.append(canonical)
    if expansions:
        return query + " " + " ".join(dict.fromkeys(expansions))
    return query
