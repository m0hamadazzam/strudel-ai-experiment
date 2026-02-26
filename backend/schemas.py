from typing import Literal, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    current_code: str = ""


class PatchOperation(BaseModel):
    op: Literal["insert", "delete", "replace"] = Field(
        ...,
        description="Patch operation type.",
    )
    start: int = Field(
        ...,
        ge=0,
        description="Start character offset (0-based, inclusive) in the base code.",
    )
    end: int = Field(
        ...,
        ge=0,
        description="End character offset (0-based, exclusive) in the base code.",
    )
    old_text: str = Field(
        default="",
        description="Text expected in base code at [start:end].",
    )
    new_text: str = Field(
        default="",
        description="Replacement text for this range.",
    )


class PatchStats(BaseModel):
    additions: int = 0
    deletions: int = 0
    operations: int = 0


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: Optional[float] = None


class ChatResponse(BaseModel):
    code: str
    explanation: str = ""
    patch_ops: list[PatchOperation] = Field(default_factory=list)
    patch_stats: PatchStats = Field(default_factory=PatchStats)
    usage: Optional[TokenUsage] = None


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
