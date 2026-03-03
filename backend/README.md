# Strudel AI Copilot Backend

FastAPI backend for the Strudel AI Copilot. It exposes copilot chat endpoints (sync and streaming) and powers RAG‑enhanced code generation in the REPL.

**Running the full app:** see the root **[README.md](../README.md)** (Getting started section). From the project root, `./start.sh` starts both backend and frontend. The backend is served as `backend.main:app` (uvicorn).

---

## 1. Environment & Configuration

- **OpenAI**: `OPENAI_API_KEY` must be set (in your environment or in `backend/.env`).
- **Optional – Langfuse tracing**: set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and optionally `LANGFUSE_BASE_URL` (default `https://cloud.langfuse.com`). If unset, tracing is skipped.

---

## 2. API Surface

The app is defined in `backend.api.app`. Endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Health check. |
| `POST` | `/api/copilot/chat` | Sync chat: request body `{ "message", "current_code"?: string }`; returns full `ChatResponse` (code, explanation, patch_ops, patch_stats). |
| `POST` | `/api/copilot/chat/stream` | Streaming chat: same body; response is NDJSON stream of events (status, reasoning, final response, error). Used by the REPL UI. |
| `POST` | `/api/copilot/interactions/{interaction_id}/feedback` | Record feedback (e.g. accepted/rejected) for an interaction. |

Request/response schemas live in `backend.core.schemas` (`ChatRequest`, `ChatResponse`, etc.).

---

## 3. Backend layout (refactored packages)

| Package / module | Role |
|------------------|------|
| `backend/main.py` | Entry point: exposes `backend.api.app` for uvicorn. |
| `backend/api/app.py` | FastAPI app, CORS, and route handlers for copilot and health. |
| `backend/core/` | Shared logic: `context_window`, `generation` (LLM + structured output), `prompts`, `routing` (prefetch/web-search heuristics), `schemas`. |
| `backend/copilot/` | Orchestration: `orchestrator` (generate → validate → repair, streaming), `validation` (Strudel/sound/args), `interactions` (logging, feedback). |
| `backend/rag/` | RAG: `retrieval` (context bundles), `vector_store`, `relationship_utils`. |
| `backend/db/` | Persistence: `models`, `session`, `init_db` (create DB/tables). |
| `backend/patching/` | `patch_utils`: compute minimal patch operations and stats. |
| `backend/scripts/` | CLI-style scripts: `import_data`, `indexing`, `validate_import`. |

---

## 4. Patch mode overview

The copilot uses a **patch mode** flow to avoid blind full‑buffer overwrites:

1. The model still generates a full candidate `code`.
2. The backend computes deterministic patch operations from `current_code → code`.
3. The API returns both the full `code` and structured patch metadata (`patch_ops`, `patch_stats`).
4. The frontend shows hunk‑level diff previews and lets the user **accept / reject** patches before they are applied.
5. Patch activation is guarded by a base‑code match to prevent applying stale diffs.

This enables reviewable, minimal edits with explicit user approval instead of auto‑applying large rewrites.

---

## 5. RAG (Retrieval‑augmented generation)

The backend uses a RAG pipeline to ground the copilot in the Strudel knowledge base (functions, presets, recipes).

### 5.1. What RAG does

1. **Index** the knowledge base into a vector store.
2. **Retrieve** relevant context based on the user’s request.
3. **Enhance** prompts with that context for more accurate code generation.

### 5.2. One‑time setup

From the project root (with your venv activated):

```bash
pip install -r backend/requirements.txt

# Create SQLite DB and tables
python -m backend.db.init_db

# Populate the knowledge base (requires doc.json at project root)
python -m backend.scripts.import_data

# Build the vector store for RAG (requires OPENAI_API_KEY)
python -m backend.scripts.indexing
# or to force‑recreate (deletes existing vector store):
python -m backend.scripts.indexing --force
```

This will:

- Create the SQLite DB and import functions, presets, and recipes.
- Generate embeddings with `text-embedding-3-small` and persist the vector store in `backend/chroma_db/`.

Optional: run `python -m backend.scripts.validate_import` to check import results.

### 5.3. RAG at runtime

The flow is implemented in `backend/copilot/orchestrator.py` (no separate LangGraph agent):

1. **Routing** (`core/routing.py`): Heuristics decide whether to prefetch KB context and whether to enable web search (no LLM).
2. **Prefetch**: If needed, `rag/retrieval.py` is called (`retrieve_relevant_context_bundle`, `retrieve_preset_context_bundle`) to get function/preset/recipe context from the vector store and DB.
3. **Prompt**: `core/prompts.py` builds messages with optional KB context; `core/context_window.py` windows conversation history.
4. **Generation**: `core/generation.py` calls the OpenAI Responses API (structured output `StrudelCodeOut`). Streaming uses `generate_with_context_stream`; repair uses `repair_with_context_stream` after validation failures.
5. **Validation**: `copilot/validation.py` checks function names, sound presets, and argument counts.
6. **Patch**: `patching/patch_utils.py` computes minimal patch operations from current code → generated code. The API returns both full `code` and `patch_ops` / `patch_stats`.

---

## 6. Data import strategy (KB)

The import pipeline fills the SQLite knowledge base used by RAG.

### 6.1. What we import

| Source | Table | Scope |
|--------|-------|-------|
| `doc.json` | `functions` | All JSDoc‑documented API from `packages/` (generated by `pnpm run jsdoc-json`), minus private/`kind: "package"` entries. |
| `website/public/*.json` | `presets` | Sample‑bank JSONs (e.g. `tidal-drum-machines`, `uzu-drumkit`, `uzu-wavetables`, `vcsl`, `mridangam`, `piano`). |
| Built‑in synths | `presets` | Names from `registerSynthSounds()` / `registerZZFXSounds()` (waveforms, sbd, supersaw, bytebeat, pulse, noises, ZZFX). |
| Inline Dirt samples | `presets` | Bank names from the prebaked Dirt sample set (casio, crow, insect, wind, jazz, metal, east, space, numbers, num). |
| Recipes | `recipes` | Tunes/examples from JS/MJS tune files and `website/src/pages/recipes/*.mdx` `<MiniRepl>` snippets. |

### 6.2. What we do *not* import

- Functions that do not appear in `doc.json` (certain internals, parse failures).
- Soundfont presets and user samples that are not covered by the listed JSONs.
- MDX content outside the recipes pages.

### 6.3. Import process (high level)

1. **Functions**: Load `doc.json` → clean & categorize (pattern, time, control, effect, signal, utility, motion, other) → insert/update `functions`.
2. **Presets**: Load sample‑bank JSONs + built‑ins → upsert into `presets` with tags and simple `s("name")` examples.
3. **Recipes**: Extract code snippets from tune files and recipes MDX → upsert into `recipes`, using `tags` (with `import:*`) to safely re‑import.

After import, you can optionally run validation scripts to check counts and data quality (see `backend/scripts/validate_import.py`).

---

## 7. Development notes

- Keep backend documentation in this `README.md`; project‑wide setup and context are in the root `README.md` and `PROJECT_PRESENTATION.md`.
- When changing RAG or generation behavior, touch `backend/rag/`, `backend/core/prompts.py`, and `backend/core/generation.py` as needed, and update this README if setup or endpoints change.

