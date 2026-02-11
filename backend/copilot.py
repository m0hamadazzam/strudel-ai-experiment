from __future__ import annotations

import re
import hashlib
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from .database import AIInteraction, AIContextCache, Function, get_session
from .prompts import build_system_prompt
from .retrieval import (
    extract_function_names_from_query,
    retrieve_relevant_context,
)
from .schemas import ChatRequest, ChatResponse, StrudelCodeOut

backend_dir = Path(__file__).parent
load_dotenv(backend_dir / ".env")

logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

DEFAULT_MODEL = "gpt-5.1-codex-mini"
MAX_OUTPUT_TOKENS = 1500
CONTEXT_CACHE_TTL_HOURS = 24

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


def _query_hash(message: str, current_code: str) -> str:
    payload = (message + "\n" + (current_code or "")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _get_cached_context(query_hash: str) -> str | None:
    session = get_session()
    try:
        from datetime import datetime
        row = session.query(AIContextCache).filter(
            AIContextCache.query_hash == query_hash,
            AIContextCache.expires_at > datetime.utcnow(),
        ).first()
        return row.context_text if row else None
    finally:
        session.close()


def _set_cached_context(query_hash: str, context_text: str) -> None:
    from datetime import datetime, timedelta
    session = get_session()
    try:
        expires = datetime.utcnow() + timedelta(hours=CONTEXT_CACHE_TTL_HOURS)
        existing = session.query(AIContextCache).filter_by(
            query_hash=query_hash
        ).first()
        if existing:
            existing.context_text = context_text
            existing.expires_at = expires
        else:
            session.add(AIContextCache(
                query_hash=query_hash,
                context_text=context_text,
                expires_at=expires,
            ))
        session.commit()
    except Exception as e:
        logger.warning("Failed to cache context: %s", e)
        session.rollback()
    finally:
        session.close()


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
        session.add(AIInteraction(
            user_query=user_query,
            generated_code=generated_code,
            applied=0,
            response_time_ms=response_time_ms,
        ))
        session.commit()
    except Exception as e:
        logger.warning("Failed to log AI interaction: %s", e)
        session.rollback()
    finally:
        session.close()


def generate_code(request: ChatRequest) -> ChatResponse:
    if not client.api_key:
        return ChatResponse(
            code=request.current_code,
            explanation="Error: OPENAI_API_KEY not set in environment",
        )

    start = time.perf_counter()
    user_query = request.message
    qhash = _query_hash(user_query, request.current_code or "")

    try:
        context = _get_cached_context(qhash)
        if context is None:
            try:
                function_names = extract_function_names_from_query(user_query)
                context = retrieve_relevant_context(
                    user_query,
                    k=4,
                    extra_function_names=function_names[:3] if function_names else None,
                )
            except Exception as e:
                logger.warning("Context retrieval failed: %s", e)
                context = ""
            if context:
                _set_cached_context(qhash, context)

        system_prompt = (
            build_system_prompt(context) if context else build_system_prompt()
        )

        resp = client.responses.parse(
            model=DEFAULT_MODEL,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": _build_user_content(request)},
            ],
            reasoning={"effort": "low"},
            text_format=StrudelCodeOut,
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )

        parsed = resp.output_parsed
        if parsed is None:
            if logger.isEnabledFor(logging.DEBUG):
                raw = getattr(resp, "output_text", None)
                logger.debug("Parse failed. Raw output: %s", raw)
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
        return ChatResponse(code=code, explanation=explanation or "Code generated successfully")

    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        _log_interaction(user_query, None, elapsed_ms)
        return ChatResponse(
            code=request.current_code,
            explanation=f"Error generating code: {str(e)}",
        )
