from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from .database import AIInteraction, Function, get_session
from .patch_utils import build_patch_operations, summarize_patch_operations
from .rag_agent import get_rag_graph
from .schemas import ChatRequest, ChatResponse, TokenUsage

# Optional Langfuse: only import and use when credentials are set
def _get_langfuse_handler():
    if not os.getenv("LANGFUSE_SECRET_KEY"):
        return None
    try:
        from langfuse import get_client
        from langfuse.langchain import CallbackHandler
        get_client()  # ensure client is initialized from env
        return CallbackHandler()
    except Exception:
        return None

backend_dir = Path(__file__).parent
load_dotenv(backend_dir / ".env")

logger = logging.getLogger(__name__)

# Substrings that indicate Node/non-Strudel code (forbidden in generated code)
FORBIDDEN_CODE_PATTERNS = (
    "require(",
    "import ",
    "process.",
    "__dirname",
    "module.exports",
)

# Regex: identifier followed by ( -> function/method call name
_RE_CALL_NAME = re.compile(r"\b([a-zA-Z_$][a-zA-Z0-9_]*)\s*\(")
_RE_METHOD_NAME = re.compile(r"\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\(")

_ALLOWED_FUNCTION_NAMES_CACHE: set[str] | None = None


def _get_allowed_function_names() -> set[str]:
    """Return set of all function names and synonyms in the knowledge base (DB). Cached."""
    global _ALLOWED_FUNCTION_NAMES_CACHE
    if _ALLOWED_FUNCTION_NAMES_CACHE is not None:
        return _ALLOWED_FUNCTION_NAMES_CACHE
    session = get_session()
    try:
        names: set[str] = set()
        for row in session.query(Function).all():
            if row.name:
                names.add(row.name)
            if row.synonyms and row.synonyms != "[]":
                try:
                    for syn in json.loads(row.synonyms) or []:
                        if isinstance(syn, str) and syn.strip():
                            names.add(syn.strip())
                except (json.JSONDecodeError, TypeError):
                    pass
        _ALLOWED_FUNCTION_NAMES_CACHE = names
        return names
    finally:
        session.close()


def _extract_called_identifiers(code: str) -> tuple[set[str], set[str]]:
    """Extract top-level call names and method names from code. Returns (names, methods)."""
    names = set(_RE_CALL_NAME.findall(code))
    methods = set(_RE_METHOD_NAME.findall(code))
    return names, methods


def _build_user_content(request: ChatRequest) -> str:
    if request.current_code:
        return (
            f"Current code:\n{request.current_code}\n\n"
            f"User request: {request.message}\n"
        )
    return request.message


def _validate_generated_code(
    code: str,
    allowed_function_names: set[str] | None = None,
) -> str | None:
    """
    Return an error message if code is invalid, else None.

    - Always rejects FORBIDDEN_CODE_PATTERNS (Node/non-Strudel).
    - If allowed_function_names is provided (from knowledge base), rejects any
      function or method call whose name is not in the KB.
    """
    for pattern in FORBIDDEN_CODE_PATTERNS:
        if pattern in code:
            return (
                "Generated code used disallowed APIs (e.g. Node.js). "
                "Please rephrase your request."
            )

    if allowed_function_names is None or len(allowed_function_names) == 0:
        return None

    names, methods = _extract_called_identifiers(code)
    for name in names:
        if name not in allowed_function_names:
            return (
                f"Generated code used '{name}', which is not in the knowledge base. "
                "Use only functions from the retrieved context or Strudel docs."
            )
    for method in methods:
        if method not in allowed_function_names:
            return (
                f"Generated code used '.{method}(...)', which is not in the knowledge base. "
                "Use only functions/methods from the retrieved context or Strudel docs."
            )
    return None


# Fallback USD per 1K tokens when Langfuse cost is not available
_COST_PER_1K = {
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-5.1-codex-mini": (0.001, 0.003),
}


def _estimate_cost_usd(input_tokens: int, output_tokens: int) -> float | None:
    """Return approximate USD cost for display. Fallback when Langfuse cost unavailable."""
    model = os.getenv("OPENAI_MODEL", "gpt-5.1-codex-mini")
    if model not in _COST_PER_1K:
        return None
    in_p, out_p = _COST_PER_1K[model]
    return (input_tokens / 1000.0) * in_p + (output_tokens / 1000.0) * out_p


def _get_langfuse_trace_cost(trace_id: str | None) -> float | None:
    """Fetch trace from Langfuse and return total_cost (USD). Returns None on any failure."""
    if not trace_id:
        return None
    try:
        from langfuse import get_client
        langfuse = get_client()
        langfuse.flush()
        trace = langfuse.api.trace.get(trace_id)
        cost = getattr(trace, "total_cost", None)
        if cost is not None and not (isinstance(cost, float) and cost < 0):
            return float(cost)
    except Exception as e:
        logger.debug("Could not get Langfuse trace cost: %s", e)
    return None


def _aggregate_usage(final_state: dict, langfuse_cost: float | None = None) -> TokenUsage:
    """Sum token usage from agent messages and code-gen state. Use langfuse_cost if provided."""
    input_total = 0
    output_total = 0
    for msg in final_state.get("messages") or []:
        um = getattr(msg, "usage_metadata", None) or {}
        if isinstance(um, dict):
            input_total += int(um.get("input_tokens") or 0)
            output_total += int(um.get("output_tokens") or 0)
    code_usage = final_state.get("usage") or {}
    if isinstance(code_usage, dict):
        input_total += int(code_usage.get("input_tokens") or 0)
        output_total += int(code_usage.get("output_tokens") or 0)
    total = input_total + output_total
    cost = langfuse_cost if langfuse_cost is not None else _estimate_cost_usd(
        input_total, output_total
    )
    return TokenUsage(
        input_tokens=input_total,
        output_tokens=output_total,
        total_tokens=total,
        estimated_cost_usd=cost,
    )


def _log_interaction(
    user_query: str,
    generated_code: str | None,
    response_time_ms: int,
) -> None:
    session = get_session()
    try:
        session.add(
            AIInteraction(
                user_query=user_query,
                generated_code=generated_code,
                applied=0,
                response_time_ms=response_time_ms,
            )
        )
        session.commit()
    except Exception as e:
        logger.warning("Failed to log AI interaction: %s", e)
        session.rollback()
    finally:
        session.close()


def generate_code(request: ChatRequest) -> ChatResponse:
    if not os.getenv("OPENAI_API_KEY"):
        return ChatResponse(
            code=request.current_code,
            explanation="Error: OPENAI_API_KEY not set in environment",
        )

    start = time.perf_counter()
    user_query = request.message

    try:
        graph = get_rag_graph()
        initial_state: dict = {
            "messages": [HumanMessage(content=_build_user_content(request))],
        }
        langfuse_handler = _get_langfuse_handler()
        trace_id = None
        if langfuse_handler:
            from langfuse import get_client
            with get_client().start_as_current_observation(
                as_type="span", name="copilot.generate_code"
            ):
                final_state = graph.invoke(
                    initial_state, config={"callbacks": [langfuse_handler]}
                )
                trace_id = get_client().get_current_trace_id()
        else:
            final_state = graph.invoke(initial_state)
        parsed = final_state.get("parsed_output")

        if parsed is None:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            _log_interaction(user_query, None, elapsed_ms)
            return ChatResponse(
                code=request.current_code,
                explanation="Error: model output did not match schema.",
            )

        code = parsed.code.strip()
        explanation = (
            (parsed.explanation or "").strip()
            if getattr(parsed, "explanation", None)
            else "Code generated successfully"
        )

        allowed_names = _get_allowed_function_names()
        err = _validate_generated_code(code, allowed_function_names=allowed_names)
        if err:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            _log_interaction(user_query, None, elapsed_ms)
            return ChatResponse(
                code=request.current_code,
                explanation=err,
            )

        patch_ops = build_patch_operations(request.current_code or "", code)
        patch_stats = summarize_patch_operations(patch_ops)
        langfuse_cost = _get_langfuse_trace_cost(trace_id)
        usage = _aggregate_usage(final_state, langfuse_cost=langfuse_cost)

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        _log_interaction(user_query, code, elapsed_ms)
        return ChatResponse(
            code=code,
            explanation=explanation or "Code generated successfully",
            patch_ops=patch_ops,
            patch_stats=patch_stats,
            usage=usage,
        )

    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        _log_interaction(user_query, None, elapsed_ms)
        return ChatResponse(
            code=request.current_code,
            explanation=f"Error generating code: {str(e)}",
        )
