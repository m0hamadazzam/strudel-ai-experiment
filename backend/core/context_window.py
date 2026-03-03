"""
Token-budgeted conversation history windowing.

Fills the history budget most-recent-first with priority-aware compression:
recent user intent is always preserved, old assistant code blocks are stripped
(current_code already reflects accepted patches).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .schemas import HistoryMessage

CHARS_PER_TOKEN = 4
DEFAULT_HISTORY_TOKEN_BUDGET = 2000


def _get_budget() -> int:
    raw = os.getenv("HISTORY_TOKEN_BUDGET")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return DEFAULT_HISTORY_TOKEN_BUDGET


def _format_message(
    msg: HistoryMessage,
    *,
    include_code: bool = True,
    truncate_explanation: bool = False,
) -> str:
    text = msg.content or ""
    if msg.role == "assistant":
        if truncate_explanation and text:
            first_line = text.split("\n", 1)[0]
            if len(first_line) < len(text):
                text = first_line
        if include_code and msg.code:
            text = f"{text}\n[code]: {msg.code}"
    return text


def window_conversation_history(
    history: list[HistoryMessage],
    token_budget: int | None = None,
) -> list[dict]:
    """Return windowed history messages that fit within the token budget.

    Strategy:
    - Most-recent-first fill.
    - Recent messages (last 2): full explanation, no code (code is redundant
      because the request includes current_code).
    - Older messages: user intent kept, assistant explanations truncated to
      first line, code stripped.
    - Hard cutoff when budget is exhausted.
    """
    if not history:
        return []

    if token_budget is None:
        token_budget = _get_budget()
    char_budget = token_budget * CHARS_PER_TOKEN

    result: list[dict] = []
    used = 0

    for age, msg in enumerate(reversed(history)):
        is_recent = age < 2

        if is_recent:
            text = _format_message(msg, include_code=False)
        else:
            text = _format_message(
                msg, include_code=False, truncate_explanation=True
            )

        if used + len(text) > char_budget:
            break

        result.insert(0, {"role": msg.role, "content": text})
        used += len(text)

    return result
