"""
LLM generation layer for the Strudel copilot.

Replaces the old LangGraph agent with direct OpenAI Responses API calls.
Two entry points:
  - generate_with_context()  — main (fast path) generation
  - repair_with_context()    — targeted repair after validation failure
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Generator, Optional

from dotenv import load_dotenv
from openai import NOT_GIVEN, OpenAI
from pydantic import ValidationError

from .prompts import build_prompt_messages, get_static_system_prompt
from .schemas import StrudelCodeOut

_backend_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_backend_dir, ".env"))

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-5.1-codex-mini"
# Reasoning models (codex-mini) use internal reasoning tokens that count against
# this budget.  8192 is too low for complex prompts — reasoning alone can consume
# several thousand tokens before the actual JSON output is produced.
MAX_OUTPUT_TOKENS = 16384

WEB_SEARCH_DOMAINS = [
    "strudel.cc",
    "strudel.learn.audio",
    "github.com",
]

_openai_client: Optional[OpenAI] = None


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _openai_client


def get_model() -> str:
    return os.getenv("OPENAI_MODEL", DEFAULT_MODEL)


def _prompt_cache_key(kind: str) -> str:
    raw = f"{get_model()}:{kind}:v1"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]
    return f"strudel:{digest}"


def _extract_usage(resp) -> dict | None:
    u = getattr(resp, "usage", None)
    if u is None:
        return None
    return {
        "input_tokens": getattr(u, "input_tokens", 0) or 0,
        "output_tokens": getattr(u, "output_tokens", 0) or 0,
        "total_tokens": getattr(u, "total_tokens", 0) or 0,
    }


# ---------------------------------------------------------------------------
# Fallback parsing when structured output_parsed is None
# ---------------------------------------------------------------------------

_STRUDEL_INDICATORS = ("s(", "note(", "stack(", "$:", "setcpm(", "sound(")
_RE_JSON_FENCED = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_raw_text(resp) -> str | None:
    """Pull the first text content from a Responses API output list."""
    for item in getattr(resp, "output", None) or []:
        for part in getattr(item, "content", None) or []:
            text = getattr(part, "text", None)
            if text:
                return text
    return None


def _try_parse_fallback(raw_text: str) -> StrudelCodeOut | None:
    """Best-effort parse of raw model text into StrudelCodeOut.

    Handles:
      1. Valid JSON that the SDK didn't wire into output_parsed.
      2. JSON wrapped in markdown code fences.
      3. A JSON object with a "code" key embedded in prose.
      4. Raw Strudel code without JSON wrapper.
    """
    if not raw_text:
        return None
    text = raw_text.strip()

    # Strategy 1 — direct JSON
    try:
        data = json.loads(text)
        if isinstance(data, dict) and data.get("code"):
            return StrudelCodeOut(**data)
    except (json.JSONDecodeError, ValidationError):
        pass

    # Strategy 2 — JSON inside ```json ... ``` fences
    m = _RE_JSON_FENCED.search(text)
    if m:
        try:
            data = json.loads(m.group(1))
            if isinstance(data, dict) and data.get("code"):
                return StrudelCodeOut(**data)
        except (json.JSONDecodeError, ValidationError):
            pass

    # Strategy 3 — find { "code": ... } anywhere in the text
    idx = text.find('"code"')
    if idx != -1:
        brace = text.rfind("{", 0, idx)
        if brace != -1:
            depth = 0
            for i in range(brace, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            data = json.loads(text[brace : i + 1])
                            if isinstance(data, dict) and data.get("code"):
                                return StrudelCodeOut(**data)
                        except (json.JSONDecodeError, ValidationError):
                            pass
                        break

    # Strategy 4 — raw text IS Strudel code (no JSON wrapper)
    # Skip if text looks like malformed JSON (starts with {)
    if not text.startswith("{") and any(ind in text for ind in _STRUDEL_INDICATORS):
        code = text
        if code.startswith("```"):
            lines = code.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            code = "\n".join(lines).strip()
        if code:
            return StrudelCodeOut(code=code)

    return None


def _parse_response(resp, caller: str) -> tuple[StrudelCodeOut | None, dict | None]:
    """Shared post-processing: try output_parsed first, then fallback."""
    usage = _extract_usage(resp)

    status = getattr(resp, "status", "completed")
    if status != "completed":
        details = getattr(resp, "incomplete_details", None)
        logger.warning("%s: response status=%s details=%s", caller, status, details)

    if resp.output_parsed is not None:
        return resp.output_parsed, usage

    raw = _extract_raw_text(resp)
    if raw:
        logger.info(
            "%s: output_parsed is None; attempting fallback (%d chars)", caller, len(raw)
        )
        fallback = _try_parse_fallback(raw)
        if fallback is not None:
            logger.info("%s: fallback parse succeeded", caller)
            return fallback, usage
        logger.warning("%s: fallback parse failed. Raw text: %.500s", caller, raw)
    else:
        logger.warning("%s: output_parsed is None and no raw text in response", caller)

    return None, usage


def _map_stream_event(event) -> dict | None:
    """Translate SDK stream events into compact UI-friendly payloads."""
    if event.type == "response.reasoning_summary_text.delta":
        delta = getattr(event, "delta", None)
        if delta:
            return {"type": "reasoning", "delta": delta}

    if event.type == "response.web_search_call.in_progress":
        return {
            "type": "status",
            "phase": "web_search",
            "message": "Checking online references.",
        }

    if event.type == "response.web_search_call.searching":
        return {
            "type": "status",
            "phase": "web_search",
            "message": "Searching Strudel docs and related sources.",
        }

    if event.type == "response.web_search_call.completed":
        return {
            "type": "status",
            "phase": "web_search",
            "message": "Online reference check complete.",
        }

    return None


def _stream_with_context(
    messages: list[dict],
    *,
    tools,
    caller: str,
) -> Generator[dict, None, tuple[StrudelCodeOut | None, dict | None]]:
    """Stream reasoning summaries and return the parsed final response."""
    client = _get_openai_client()
    model = get_model()
    prompt_cache_key = _prompt_cache_key(caller)
    resp = None

    try:
        with client.responses.stream(
            model=model,
            input=messages,
            text_format=StrudelCodeOut,
            tools=tools,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            prompt_cache_key=prompt_cache_key,
            reasoning={"summary": "detailed"},
        ) as stream:
            for event in stream:
                payload = _map_stream_event(event)
                if payload is not None:
                    yield payload
            resp = stream.get_final_response()
    except Exception as e:
        logger.warning("%s failed: %s", caller, e)
    else:
        parsed, usage = _parse_response(resp, caller)
        if parsed is not None:
            return parsed, usage
        logger.warning("%s: streamed response had no parseable final payload", caller)

    yield {
        "type": "status",
        "phase": "recovery",
        "message": "Recovering final response.",
    }

    try:
        resp = client.responses.parse(
            model=model,
            input=messages,
            text_format=StrudelCodeOut,
            tools=tools,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            prompt_cache_key=prompt_cache_key,
        )
    except Exception as e:
        logger.warning("%s recovery failed: %s", caller, e)
        return None, None

    return _parse_response(resp, f"{caller}:recovery")


# ---------------------------------------------------------------------------
# Generation entry points
# ---------------------------------------------------------------------------


def generate_with_context(
    user_content: str,
    kb_context: str,
    conversation_history: list[dict],
    enable_web_search: bool,
) -> tuple[StrudelCodeOut | None, dict | None]:
    """Single LLM call for code generation.

    Returns (parsed_output, usage_dict). parsed_output is None on failure.
    """
    client = _get_openai_client()
    model = get_model()
    messages = build_prompt_messages(kb_context, conversation_history, user_content)

    tools = NOT_GIVEN
    if enable_web_search:
        tools = [
            {
                "type": "web_search",
                "filters": {"allowed_domains": WEB_SEARCH_DOMAINS},
            }
        ]

    def _do_parse():
        return client.responses.parse(
            model=model,
            input=messages,
            text_format=StrudelCodeOut,
            tools=tools,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            prompt_cache_key=_prompt_cache_key("generate"),
        )

    try:
        if os.getenv("LANGFUSE_SECRET_KEY"):
            try:
                from langfuse import get_client

                with get_client().start_as_current_observation(
                    as_type="span", name="generation.generate_with_context"
                ):
                    resp = _do_parse()
            except Exception:
                resp = _do_parse()
        else:
            resp = _do_parse()
    except Exception as e:
        logger.warning("generate_with_context failed: %s", e)
        return None, None

    return _parse_response(resp, "generate_with_context")


def generate_with_context_stream(
    user_content: str,
    kb_context: str,
    conversation_history: list[dict],
    enable_web_search: bool,
) -> Generator[dict, None, tuple[StrudelCodeOut | None, dict | None]]:
    """Streaming variant of generate_with_context()."""
    messages = build_prompt_messages(kb_context, conversation_history, user_content)

    tools = NOT_GIVEN
    if enable_web_search:
        tools = [
            {
                "type": "web_search",
                "filters": {"allowed_domains": WEB_SEARCH_DOMAINS},
            }
        ]

    return (yield from _stream_with_context(
        messages,
        tools=tools,
        caller="generate_with_context_stream",
    ))


def repair_with_context(
    user_content: str,
    draft_code: str,
    kb_context: str,
    validation_errors: list[str],
    conversation_history: list[dict],
) -> tuple[StrudelCodeOut | None, dict | None]:
    """Focused repair call: fix specific validation errors using targeted KB docs.

    The static system prompt prefix is reused (cacheable).
    """
    client = _get_openai_client()
    model = get_model()

    error_summary = "\n".join(f"- {e}" for e in validation_errors)
    repair_prompt = (
        f"Your previous code draft had validation errors:\n{error_summary}\n\n"
        f"Draft code:\n{draft_code}\n\n"
        f"Fix the code using only the functions and sound presets documented below. "
        f"Replace any invalid function or sound name with the closest correct "
        f"alternative from the reference.\n\n"
        f"Reference docs:\n{kb_context}"
    )

    messages: list[dict] = [
        {"role": "developer", "content": get_static_system_prompt()},
        *conversation_history,
        {"role": "user", "content": user_content},
        {"role": "assistant", "content": draft_code},
        {"role": "user", "content": repair_prompt},
    ]

    def _do_repair():
        return client.responses.parse(
            model=model,
            input=messages,
            text_format=StrudelCodeOut,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            prompt_cache_key=_prompt_cache_key("repair"),
        )

    try:
        if os.getenv("LANGFUSE_SECRET_KEY"):
            try:
                from langfuse import get_client

                with get_client().start_as_current_observation(
                    as_type="span", name="generation.repair_with_context"
                ):
                    resp = _do_repair()
            except Exception:
                resp = _do_repair()
        else:
            resp = _do_repair()
    except Exception as e:
        logger.warning("repair_with_context failed: %s", e)
        return None, None

    return _parse_response(resp, "repair_with_context")


def repair_with_context_stream(
    user_content: str,
    draft_code: str,
    kb_context: str,
    validation_errors: list[str],
    conversation_history: list[dict],
) -> Generator[dict, None, tuple[StrudelCodeOut | None, dict | None]]:
    """Streaming variant of repair_with_context()."""
    error_summary = "\n".join(f"- {e}" for e in validation_errors)
    repair_prompt = (
        f"Your previous code draft had validation errors:\n{error_summary}\n\n"
        f"Draft code:\n{draft_code}\n\n"
        f"Fix the code using only the functions and sound presets documented below. "
        f"Replace any invalid function or sound name with the closest correct "
        f"alternative from the reference.\n\n"
        f"Reference docs:\n{kb_context}"
    )

    messages: list[dict] = [
        {"role": "developer", "content": get_static_system_prompt()},
        *conversation_history,
        {"role": "user", "content": user_content},
        {"role": "assistant", "content": draft_code},
        {"role": "user", "content": repair_prompt},
    ]

    return (yield from _stream_with_context(
        messages,
        tools=NOT_GIVEN,
        caller="repair_with_context_stream",
    ))
