from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .copilot import generate_code
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
