# Strudel AI Copilot Backend

FastAPI backend for the Strudel AI Copilot. Exposes the `/api/copilot/chat` endpoint and RAG agent.

**Setup and running the full app (backend + frontend):** see root **[GETTING_STARTED.md](../GETTING_STARTED.md)**. Use **`./start.sh`** from the project root to start both with one command.

**RAG agent and knowledge base:** see **[RAG_SETUP.md](RAG_SETUP.md)**.

## API

- `POST /api/copilot/chat` – Chat request (message, optional current_code); returns generated code, explanation, and patch metadata (`patch_ops`, `patch_stats`) for minimal-apply workflows.
- `GET /` – Health check.

Requires `OPENAI_API_KEY` in `backend/.env`.

**Optional – Langfuse:** Set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and optionally `LANGFUSE_BASE_URL` (default `https://cloud.langfuse.com`) to enable tracing for LLM calls. If unset, tracing is skipped.
