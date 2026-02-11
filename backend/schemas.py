from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    current_code: str = ""


class ChatResponse(BaseModel):
    code: str
    explanation: str = ""


class StrudelCodeOut(BaseModel):
    code: str = Field(
        ...,
        min_length=1,
        description="ONLY runnable Strudel JavaScript. No prose, markdown, or comments.",
    )
    explanation: Optional[str] = Field(
        default=None,
        description="Optional one-line explanation of what the code does.",
    )
