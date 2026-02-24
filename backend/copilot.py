from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from .database import AIInteraction, Function, get_session
from .rag_agent import get_rag_graph
from .schemas import ChatRequest, ChatResponse

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
    """Return set of all function names in the knowledge base (DB). Cached."""
    global _ALLOWED_FUNCTION_NAMES_CACHE
    if _ALLOWED_FUNCTION_NAMES_CACHE is not None:
        return _ALLOWED_FUNCTION_NAMES_CACHE
    session = get_session()
    try:
        names = {row.name for row in session.query(Function.name).all() if row.name}
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

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        _log_interaction(user_query, code, elapsed_ms)
        return ChatResponse(
            code=code, explanation=explanation or "Code generated successfully"
        )

    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        _log_interaction(user_query, None, elapsed_ms)
        return ChatResponse(
            code=request.current_code,
            explanation=f"Error generating code: {str(e)}",
        )
