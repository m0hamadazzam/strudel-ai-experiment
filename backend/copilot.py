import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from .prompts import SYSTEM_PROMPT
from .schemas import ChatRequest, ChatResponse, StrudelCodeOut

backend_dir = Path(__file__).parent
load_dotenv(backend_dir / ".env")

# use 5-mini with structured output method parse not create
# modify the reasoning of the model check docs
# check langchain docs for rag agents
# order to work:
#   update prompt and structured output, use gpt 5 mini, then apply rag agent
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

DEFAULT_MODEL = "gpt-5-codex"


def _build_user_content(request: ChatRequest) -> str:
    if request.current_code:
        return (
            f"Current code:\n{request.current_code}\n\n"
            f"User request: {request.message}\n"
        )
    return request.message


def generate_code(request: ChatRequest) -> ChatResponse:
    if not client.api_key:
        return ChatResponse(
            code=request.current_code,
            explanation="Error: OPENAI_API_KEY not set in environment",
        )

    try:
        resp = client.responses.parse(
            model=DEFAULT_MODEL,
            instructions=SYSTEM_PROMPT,
            input=_build_user_content(request),
            reasoning={"effort": "medium"},
            text_format=StrudelCodeOut,
            max_output_tokens=1200,
        )

        parsed = resp.output_parsed
        if parsed is None:
            return ChatResponse(
                code=request.current_code, 
                explanation="Error: empty output"
                )

        return ChatResponse(
            code=parsed.code.strip(), 
            explanation="Code generated successfully"
            )

    except Exception as e:
        return ChatResponse(
            code=request.current_code,
            explanation=f"Error generating code: {str(e)}",
        )
