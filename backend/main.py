import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .copilot import generate_code, generate_code_stream
from .schemas import ChatRequest, ChatResponse

app = FastAPI(title="Strudel AI Copilot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4321", "http://localhost:3000"],
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
