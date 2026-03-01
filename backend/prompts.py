"""
Prompt builder for the Strudel.cc AI copilot.

Static system prompt (with categorized function list + alias hints) is
generated once at startup and never changes between requests, enabling
OpenAI prompt prefix caching.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict

from .database import Function, get_session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Natural-language alias hints (static, appended to cached system prompt)
# ---------------------------------------------------------------------------

NATURAL_LANGUAGE_ALIASES = """\
Common aliases (use the Strudel name on the right):
  low pass filter / lowpass -> lpf
  high pass filter / highpass -> hpf
  band pass filter / bandpass -> bpf
  reverb -> room (dry/wet mix), rev (reverb send)
  distortion -> distort (alias: dist)
  volume / loudness -> gain
  panning -> pan
  bit crush -> crush
  chorus -> chorus
  phaser -> phaser (alias: ph)
  delay -> delay, delayfeedback (dfb), delaytime (dt)
  attack / decay / sustain / release -> attack (att), decay, sustain, release"""

# ---------------------------------------------------------------------------
# Categorized function list (generated once from DB, cached)
# ---------------------------------------------------------------------------

_CATEGORIZED_FUNCTION_LIST: str | None = None


def _get_categorized_function_list() -> str:
    """Build a categorized function-name list from the DB. Cached after first call."""
    global _CATEGORIZED_FUNCTION_LIST
    if _CATEGORIZED_FUNCTION_LIST is not None:
        return _CATEGORIZED_FUNCTION_LIST

    session = get_session()
    try:
        funcs: list[Function] = list(session.query(Function).all())
    finally:
        session.close()

    groups: dict[str, list[str]] = defaultdict(list)
    for f in funcs:
        if not f.name:
            continue
        cat = f.category or "other"
        groups[cat].append(f.name)

    _DISPLAY_ORDER = [
        "pattern",
        "time",
        "control",
        "signal",
        "effect",
        "utility",
        "motion",
        "other",
    ]

    lines: list[str] = []
    for cat in _DISPLAY_ORDER:
        names = groups.get(cat)
        if not names:
            continue
        lines.append(f"{cat}: {', '.join(sorted(names))}")

    for cat in sorted(groups):
        if cat not in _DISPLAY_ORDER:
            lines.append(f"{cat}: {', '.join(sorted(groups[cat]))}")

    _CATEGORIZED_FUNCTION_LIST = "\n".join(lines)
    return _CATEGORIZED_FUNCTION_LIST


# ---------------------------------------------------------------------------
# Key function signatures (generated from DB, cached)
# ---------------------------------------------------------------------------

_KEY_SIGNATURES: str | None = None


def _get_key_signatures() -> str:
    """Build compact signatures for multi-arg functions from the DB. Cached.

    Focuses on functions whose params include a callback/transform, since
    those are the ones the LLM most often calls with too few arguments.
    """
    global _KEY_SIGNATURES
    if _KEY_SIGNATURES is not None:
        return _KEY_SIGNATURES

    session = get_session()
    try:
        entries: list[tuple[bool, str, str]] = []
        for func in session.query(Function).all():
            if not func.name or not func.params or func.params in ("[]", "{}", "null", ""):
                continue
            try:
                params = json.loads(func.params)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(params, list) or len(params) < 2:
                continue

            pnames = [
                p.get("name", "?") for p in params if isinstance(p, dict)
            ]
            has_func_param = any(
                isinstance(p, dict)
                and "function" in str(p.get("type", {}).get("names", []))
                for p in params
            )

            ex = ""
            if func.examples and func.examples != "[]":
                try:
                    exs = json.loads(func.examples)
                    if exs and isinstance(exs[0], str):
                        ex = exs[0].split("\n")[0][:100]
                except (json.JSONDecodeError, TypeError):
                    pass

            if not ex:
                continue

            sig = f"  .{func.name}({', '.join(pnames)})"
            if ex:
                sig += f"  e.g. {ex}"
            entries.append((has_func_param, func.name, sig))

        entries.sort(key=lambda e: (not e[0], e[1]))
        selected = [e[2] for e in entries[:20]]
        _KEY_SIGNATURES = "\n".join(selected)
        return _KEY_SIGNATURES
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Static system prompt (identical every request -> prefix-cached by OpenAI)
# ---------------------------------------------------------------------------

_STATIC_SYSTEM_PROMPT: str | None = None


def get_static_system_prompt() -> str:
    """Return the static system prompt. Generated once, then cached."""
    global _STATIC_SYSTEM_PROMPT
    if _STATIC_SYSTEM_PROMPT is not None:
        return _STATIC_SYSTEM_PROMPT

    fn_list = _get_categorized_function_list()
    key_sigs = _get_key_signatures()

    _STATIC_SYSTEM_PROMPT = f"""\
You are a Strudel.cc live-coding copilot. Produce runnable Strudel JavaScript for the Strudel REPL.
Put ONLY runnable Strudel JavaScript in the `code` field. No prose, markdown, or comments inside `code`.
You may put an optional one-line summary in the `explanation` field.

Strudel facts (ground truth):
- Strudel is JavaScript plus a pattern DSL (TidalCycles-style). Patterns: s(...), note(...), n(...), stack(...), cat(...), seq(...), stepcat(...), arrange(...). Chain with .transform(...).
- Mini-notation: "bd sd", "<bd sd>", "bd(3,8)", "hh*8", "x@3 y@1", "[a b]". Operators: * / ! @ <> ~ : and (pulses,steps) for Euclidean.
- Parallel: $: s("bd sd") or $: note("c eb g").
- Default drum sounds: bd (kick), sd (snare), hh (hi-hat), oh (open hat), cp (clap), rim (rimshot), lt (low tom), mt (mid tom), ht (high tom), cr (crash), rd (ride). Banks: e.g. RolandTR808_bd, RolandTR909_sd. When reference docs list specific presets, use those exact names.
- Tempo is always given in BPM. Convert using setcpm(BPM/4). Never simplify the division. Default: 120 BPM -> setcpm(120/4).

Available Strudel functions (use ONLY these):
{fn_list}

{NATURAL_LANGUAGE_ALIASES}

Key function signatures (provide ALL required arguments):
{key_sigs}

Hard rules:
1) `code` must contain ONLY runnable Strudel JavaScript. No require(), import, process., __dirname, module.exports, or other Node/browser APIs not part of Strudel.
2) Never invent APIs. Use only functions from the list above.
3) Never invent sound/preset names. Inside s("...") use ONLY valid preset names: the defaults above (bd, sd, hh, oh, cp, rim, lt, mt, ht, cr, rd) or names from the reference docs. Common mistakes: "sn" is wrong (use "sd"), "kick" is wrong (use "bd"), "hihat" is wrong (use "hh").
4) Always provide ALL required arguments. Functions like .when(cond, transform), .every(n, transform), .off(time, transform) need BOTH the condition/value AND the transform function. Never omit the transform callback.
5) Prefer variables for layers; combine with stack(...) or $:. Use .fast(), .slow(), Euclidean mini-notation. Default drum names (bd, sd, hh) if unspecified.
6) No randomness unless requested (then use choose, wchoose, degradeBy).
7) When current code is provided, preserve unchanged lines exactly. Apply only the smallest set of edits needed for the user request.
8) For additive requests (e.g. add melody/bass/percussion/effects), keep existing parts and add new layers on top instead of rewriting.
9) setcpm is global, never .setcpm() on a pattern.
10) evenly spaced N hits -> one sound + .fast(N), no genre names.

If the request is ambiguous, make a reasonable assumption and return valid Strudel code. Do not ask questions."""

    return _STATIC_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Message builder for the Responses API
# ---------------------------------------------------------------------------


def build_prompt_messages(
    kb_context: str,
    conversation_history: list[dict],
    user_content: str,
) -> list[dict]:
    """Assemble the full input message list for the OpenAI Responses API.

    Layout:
      [developer] static system prompt   <- prefix-cached by OpenAI
      [developer] KB reference docs       <- only when KB context provided
      ... conversation history ...        <- windowed
      [user] current code + user request
    """
    messages: list[dict] = [
        {"role": "developer", "content": get_static_system_prompt()},
    ]
    if kb_context:
        messages.append(
            {"role": "developer", "content": f"Reference docs:\n{kb_context}"}
        )
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_content})
    return messages
