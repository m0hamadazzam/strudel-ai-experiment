# Getting Started – Strudel AI Copilot

One place for setup and running the app (backend + frontend).

## Prerequisites

- **Node.js** 18+
- **pnpm** (or npm)
- **Python** 3.9+
- **OpenAI API key** (for the copilot)

## One-time setup

From the **project root** (`/strudel`):

### 1. Backend (Python)

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install backend dependencies
pip install -r backend/requirements.txt
```

Create `backend/.env` with your API key:

```
OPENAI_API_KEY=sk-...
```

### 2. Frontend (Node)

```bash
pnpm install
```

### 3. Optional – RAG and knowledge base (recommended)

So the copilot can use the Strudel function reference and validation:

```bash
# With .venv activated, from project root
cd backend && python init_db.py && cd ..
cd backend && python import_data.py && cd ..
python -m backend.indexing
```

- `init_db.py` creates the SQLite DB and tables.
- `import_data.py` imports functions from `doc.json` (must exist at project root).
- `indexing` builds the vector store for the RAG agent (requires `OPENAI_API_KEY`).

For RAG architecture and troubleshooting, see [backend/RAG_SETUP.md](backend/RAG_SETUP.md).

## Run the app (one command)

From the project root (macOS/Linux):

```bash
./start.sh
```

On Windows, use the two-terminal option below.

- Starts the **backend** at http://localhost:8000
- Starts the **frontend** at http://localhost:4321
- Press **Ctrl+C** to stop both.

Then open **http://localhost:4321** and use the copilot sidebar (it talks to the backend).

### Without the script (two terminals)

**Terminal 1 – backend:**

```bash
source .venv/bin/activate
python -m uvicorn backend.main:app --reload --port 8000
```

**Terminal 2 – frontend:**

```bash
pnpm run start
```

## Testing

Backend tests (with venv activated, from project root):

```bash
python -m pytest backend/tests -v
```

## Troubleshooting

- **Backend / copilot does nothing** – If `./start.sh` shows "Backend may not have started", the backend likely failed (e.g. missing `OPENAI_API_KEY`, wrong Python path). Run the backend in a separate terminal to see errors: `source .venv/bin/activate && python3 -m uvicorn backend.main:app --reload --port 8000` (from project root). In the browser, open DevTools (F12) → Network and retry the copilot; check for failed requests to `http://localhost:8000/api/copilot/chat`.
- **"OPENAI_API_KEY not set"** – Add it to `backend/.env`.
- **Port 8000 or 4321 in use** – Stop the other process or change the port in `start.sh` / the uvicorn and Astro commands.
- **Copilot returns errors** – Ensure the backend is running and the frontend points to `http://localhost:8000` (see `website/src/repl/components/AICopilotSidebar.jsx`).
- **RAG / "not in the knowledge base"** – Run the optional RAG setup (init_db, import_data, indexing). See [backend/RAG_SETUP.md](backend/RAG_SETUP.md).
- **Import or indexing fails** – Ensure `doc.json` exists at project root (`pnpm run jsdoc-json` or `npm run jsdoc-json` generates it).
