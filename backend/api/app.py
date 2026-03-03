import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from ..copilot import generate_code, generate_code_stream, record_interaction_feedback
from ..core.schemas import (
    ChatRequest,
    ChatResponse,
    InteractionFeedbackRequest,
    InteractionFeedbackResponse,
)


app = FastAPI(title="Strudel AI Copilot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4321", "http://localhost:3000"],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok", "message": "Strudel AI Copilot API"}


@app.post("/api/copilot/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    return generate_code(request)


@app.post("/api/copilot/chat/stream")
def chat_stream(request: ChatRequest):
    def event_stream():
        for event in generate_code_stream(request):
            yield json.dumps(event) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.post(
    "/api/copilot/interactions/{interaction_id}/feedback",
    response_model=InteractionFeedbackResponse,
)
def interaction_feedback(interaction_id: int, request: InteractionFeedbackRequest):
    try:
        return record_interaction_feedback(interaction_id, status=request.status)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

