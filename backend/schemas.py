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
        description="Runnable Strudel JavaScript code."
    )
