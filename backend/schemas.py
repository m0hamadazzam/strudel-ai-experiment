from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    current_code: str = ""


class ChatResponse(BaseModel):
    code: str
    explanation: str = ""
