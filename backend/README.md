# Strudel AI Copilot Backend

FastAPI backend for the Strudel AI Copilot. Exposes the `/api/copilot/chat` endpoint and RAG agent.

**Setup and running the full app (backend + frontend):** see root **[GETTING_STARTED.md](../GETTING_STARTED.md)**. Use **`./start.sh`** from the project root to start both with one command.

**RAG agent and knowledge base:** see **[RAG_SETUP.md](RAG_SETUP.md)**.

## API

- `POST /api/copilot/chat` – Chat request (message, optional current_code); returns code and explanation.
- `GET /` – Health check.

Requires `OPENAI_API_KEY` in `backend/.env`.
