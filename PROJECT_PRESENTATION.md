# Strudel AI Copilot — Project Presentation

A single document explaining what this app is, what Strudel is, what was built (backend + chat interface), how the copilot works, and why it is designed this way. Intended for presenting the full project.

---

## 1. What Is This App?

This repository is an **experimental AI-assisted live-coding environment** built as a **Masterschool Software & AI Engineering graduation project**. It is a **personal educational project**, not an official Strudel feature or a commercial product.

**In one sentence:**  
A fork of the Strudel REPL with a **right-hand AI Copilot sidebar** that helps you write and modify Strudel patterns via natural language, with strict validation, RAG (docs + recipes + presets), and **reviewable patch-based edits** instead of full-buffer overwrites.

**What the app does for the user:**
- You type what you want in the copilot chat (e.g. “add a snare on the backbeat”, “use a low pass filter”).
- The backend uses an LLM plus a Strudel knowledge base to generate **valid Strudel code**.
- The UI shows **diffs (patches)** so you can accept or reject each change **per hunk** in the chat or inline in the editor.
- Accepted changes are applied to the REPL editor; you can run the pattern immediately.

---

## 2. What Is Strudel?

**Strudel** is an open-source, **browser-based live-coding music environment** inspired by TidalCycles. Musicians write code to create and manipulate musical patterns in real time.

- **Website:** https://strudel.cc  
- **Try it:** https://strudel.cc  
- **Docs:** https://strudel.cc/learn  
- **License:** GNU AGPL-3.0  

**Key ideas:**
- Patterns are expressed in **mini-notation** (e.g. `"bd sd hh"` for kick, snare, hi-hat).
- You use functions like `s()`, `stack()`, `slow()`, `gain()`, `.bank()`, effects like `.lpf()`, `.room()`, etc.
- Code runs in the browser; changing code updates the pattern live.

This project is a **fork of Strudel for local experimentation only**. The fork adds the AI copilot sidebar and the backend; it does **not** modify Strudel’s core musical engine. The AI layer is **decoupled** so it could be removed or reused elsewhere.

---

## 3. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Browser (Frontend)                                                      │
│  ┌──────────────────────────────┐  ┌─────────────────────────────────┐ │
│  │  Strudel REPL (fork)         │  │  AI Copilot (website/.../copilot/)│
│  │  - Code editor (CodeMirror)  │  │  - AICopilotSidebar, MessageList   │ │
│  │  - Eval / audio              │  │  - CopilotInput, ThinkingIndicator│ │
│  │  - setPatchReview / hunks     │  │  - Stream NDJSON, per-hunk UI     │ │
│  │  - getCode / setCode          │  │  - Session usage, feedback API   │ │
│  └──────────────┬───────────────┘  └────────────────┬──────────────────┘ │
│                 │  context.editorRef, activeCode      │                    │
│                 └────────────────────────────────────┘                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │  POST /api/copilot/chat, /chat/stream, feedback
                                    │  Body: message, current_code, conversation_history
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Backend (Python, FastAPI) — http://localhost:8000                        │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │  api/app.py        → FastAPI app, CORS, route handlers                ││
│  │  main.py           → exposes api.app for uvicorn                    ││
│  │  copilot/           → orchestrator, validation, interactions        ││
│  │  core/              → generation, prompts, routing, context_window,  ││
│  │                       schemas                                        ││
│  │  rag/               → retrieval, vector_store, relationship_utils    ││
│  │  db/                → models, session, init_db                       ││
│  │  patching/          → patch_utils (build_patch_operations, etc.)    ││
│  │  scripts/           → import_data, indexing, validate_import        ││
│  └─────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

**Separation of concerns:**
- **Frontend:** Strudel REPL + sidebar. Reads/writes editor code; shows patches; no LLM logic.
- **Backend:** All AI logic: prompts, LLM, validation, repair, RAG, patches, logging. Can run without the Strudel frontend (e.g. different clients).

---

## 4. Stack and Tools

### Frontend
- **Framework:** Astro + React (JSX)
- **Strudel:** Fork of https://github.com/tidalcycles/strudel (monorepo: `@strudel/core`, `@strudel/codemirror`, etc.)
- **Editor:** CodeMirror via `@strudel/codemirror`
- **UI:** Tailwind-style classes, Heroicons, `cx` for classnames
- **State:** React `useState` / `useRef` for chat, messages, patch state; settings via `@nanostores/persistent`

### Backend
- **Runtime:** Python 3.9+
- **API:** FastAPI, uvicorn
- **LLM:** OpenAI API (e.g. `gpt-5.1-codex-mini` or `gpt-4o-mini`), structured output / fallback parsing
- **Database:** SQLite via SQLAlchemy (functions, presets, recipes, relationships, AI interactions)
- **RAG:** Chroma (vector store), LangChain (`OpenAIEmbeddings`, `Document`), text-embedding-3-small
- **Env:** `python-dotenv`, `OPENAI_API_KEY`, optional `OPENAI_MODEL`, `HISTORY_TOKEN_BUDGET`; optional Langfuse keys for tracing

### DevOps / Run
- **Start:** `./start.sh` (backend + frontend from project root)
- **Backend:** `uvicorn backend.main:app --reload --port 8000`
- **Frontend:** `pnpm run dev` (Astro), typically http://localhost:4321

---

## 5. How the Copilot Works (End-to-End)

### 5.1 User Flow

1. User types a message in the copilot sidebar (e.g. “add reverb to the drums”).
2. Frontend sends `POST /api/copilot/chat/stream` with:
   - `message`
   - `current_code` (editor content)
   - `conversation_history` (recent user/assistant messages).
3. Backend runs the **generate → validate → repair → patch** pipeline (see below).
4. Backend streams NDJSON events: `status`, optional `reasoning`, then `final` with the full response.
5. Frontend parses the stream, builds an assistant message with `code`, `explanation`, `patch_ops`, `patch_stats`, `interaction_id`, etc.
6. Frontend shows a **diff-style preview** (per hunk: removed / added lines) and “Show in editor”, “Accept all”, “Reject all”, and per-hunk Accept/Reject.
7. When the user accepts or rejects hunks (in chat or in the editor), the editor content is updated and optional **feedback** is sent to `POST /api/copilot/interactions/{id}/feedback` with `accepted` / `partial` / `rejected`.

### 5.2 Backend pipeline (orchestration in `backend/copilot/orchestrator.py`)

**Steps:**

1. **Conversation windowing**  
   `window_conversation_history()` keeps the last N tokens of history (configurable). Recent messages keep full text; older ones are truncated and code is dropped (since `current_code` is already sent).

2. **Routing (no LLM)** — `backend/core/routing.py`:  
   - **Sound types:** `detect_sound_types(message)` → drum suffixes (bd, sd, hh, …) and whether synths are needed.  
   - **KB prefetch:** `should_prefetch_kb(message, allowed_names)` → if the user mentions code-like tokens, API questions, known function names, or effect/sound aliases, the backend will prefetch RAG context.  
   - **Web search:** `should_enable_web_search(message, kb_context)` → e.g. if the user asks for “docs” or the prefetched context is very small.

3. **Conditional RAG prefetch** — `backend/rag/retrieval.py`. If prefetch is enabled:
   - Query is expanded with aliases (e.g. “low pass” → “lpf”).
   - `retrieve_relevant_context_bundle()` runs: **Chroma** vector search → get IDs → **hydrate from SQLite** (functions, recipes, presets). SQLite is the source of truth; Chroma is only an index.
   - Optional preset context: `retrieve_preset_context_bundle(sound_types, include_synths)` so the model sees valid `s("...")` preset names.

4. **Single LLM call (fast path)**  
   - `generate_with_context()` / `generate_with_context_stream()` in `backend/core/generation.py`: builds messages from static system prompt (`core/prompts.py`) + optional KB context + windowed history (`core/context_window.py`) + user content (“Current code: … User request: …”).  
   - Calls OpenAI (Responses API), parses JSON for `{ code, explanation }` (with fallbacks for markdown-wrapped or raw code).  
   - Optional: web search tool can be attached when routing says so.

5. **Validation** — `backend/copilot/validation.py`:  
   - **Forbidden patterns:** e.g. `require(`, `import `, `process.` (no Node/non-Strudel).  
   - **Allowed functions:** Only names from the KB (and a small set of JS builtins). Extracts called names from the generated code and checks against the DB.  
   - **Sound presets:** All tokens inside `s("...")` must be in the presets table (or already in the user’s current code).  
   - **Function arity:** `get_function_signatures()` from DB; each call site is checked for minimum (and optionally maximum) arguments.

6. **Repair path (if validation fails)**  
   - Collect invalid function names, misused functions, invalid presets.  
   - Fetch **targeted** KB context for those names only (`retrieve_context_for_functions()`, preset list).  
   - `repair_with_context()` / `repair_with_context_stream()` in `core/generation.py`: same model, draft + errors + repair context → fixed version.  
   - Re-validate. If still failing, the backend can still return the repaired code with a warning.

7. **Patch building**  
   - `build_patch_operations(current_code, generated_code)` in `backend/patching/patch_utils.py`: **line-based** diff (Python `SequenceMatcher`) → list of `PatchOperation` (insert/delete/replace with `start`, `end`, `old_text`, `new_text`).  
   - `summarize_patch_operations()` → `patch_stats` (additions, deletions, operation count).

8. **Response**  
   - `ChatResponse`: `code`, `explanation`, `patch_ops`, `patch_stats`, `usage`, `interaction_id`.  
   - Every request is logged via `backend/copilot/interactions.py` (AIInteraction: query, code, response time, path_taken, tokens).  
   - Feedback endpoint updates `user_feedback` and `applied`, and triggers recomputation of usage/success stats for functions, presets, and recipes.

**Streaming variant:**  
`generate_code_stream()` in `copilot/orchestrator.py` does the same pipeline and yields NDJSON events so the UI can show “Preparing request”, “Loading relevant Strudel reference docs”, “Planning next moves”, “Validating …”, “Building a patch preview”, and finally the `final` payload.

---

## 6. How the chat interface is built (frontend)

### 6.1 Components under `website/src/repl/components/copilot/`

- **`AICopilotSidebar.jsx`** — Main container: receives `context` (editorRef, activeCode) to read/write REPL code. Holds `messages`, `input`, `isLoading`, `activePatchMessageId`, `liveAssistant` (phase/reasoning), `sessionUsage`. Calls `POST /api/copilot/chat/stream` with message, current_code, conversation_history; parses NDJSON via `readNdjsonStream`; handles status, reasoning, final, error. Sends feedback to `POST /api/copilot/interactions/{id}/feedback` when the user has accepted/rejected all hunks for that message.
- **`CopilotMessageList.jsx`** — Renders the message list (user/assistant), patch stats, token usage, cost; per-message diff preview and hunk actions.
- **`CopilotInput.jsx`** — Chat input and send.
- **`CopilotThinkingIndicator.jsx`** — Shows "Thinking" state, optional "Web" badge, and live reasoning text (sanitized) during streaming.
- **`copilotShared.js`** — Shared helpers: hunk constants, `summarizeHunks`, `buildHunkPreview`, `formatTokens`, `formatCost`, `sanitizeReasoningText`.

### 6.2 Patch / Hunk Model

- **Hunk:** `{ id, op, start, end, oldText, newText, status }` with `status` in `pending` | `accepted` | `rejected`.
- **From API:** `patch_ops` are turned into hunks with `buildPatchHunks(messageId, patchOps)`.
- **Preview:** `buildHunkPreview(hunk)` produces line lists with `type: 'remove'` or `'add'` for the chat diff.
- **Editor:** The sidebar calls `editorRef.current.setPatchReview(pendingHunks)` so the editor can show inline review (e.g. red for delete, green for add) and expose `acceptPatchHunk(hunkId)` / `rejectPatchHunk(hunkId)`.
- **Sync:** Editor can dispatch a custom event (`PATCH_ACTION_EVENT`) with `{ source: 'editor', hunkId, action, applied }`; the sidebar listens and updates hunk status so chat and editor stay in sync.
- **Base-code guard:** Before applying or showing a patch in the editor, the sidebar checks that `getLiveCode() === target.baseCode` so stale patches are not applied after the user edited the code.

### 6.3 UX Details

- Resizable sidebar (width persisted).
- Session token and cost display.
- Per-message: patch stats (operations, +/− lines), token usage, cost.
- Buttons: “Show in editor”, “Accept all”, “Reject all”, and per-hunk Accept/Reject in the chat.
- “Reviewing in editor” when that message’s hunks are the active patch in the editor.
- After all hunks are decided, feedback is sent in the background; “feedback sent” can be shown to avoid duplicate calls.

---

## 7. Why It’s Built This Way (Design Rationale)

### 7.1 Backend

- **FastAPI:** Simple, async-friendly, automatic OpenAPI, easy to add more endpoints (e.g. health, metrics).
- **Single LLM call when possible:** Avoids multi-step agents for most requests; keeps latency and cost predictable. Repair is a second call only when validation fails.
- **RAG with SQLite + Chroma:**  
  - **SQLite** = source of truth (functions, presets, recipes, relationships, interactions). Easy to inspect, backup, and evolve.  
  - **Chroma** = semantic index by embedding; returns IDs; backend hydrates full records from SQLite. This keeps correctness and updates in one place (DB) and uses vectors only for retrieval.
- **Strict validation:** Only allow functions and presets that exist in the KB (and a small JS allowlist). Reduces bad or unsafe code; repair step fixes many LLM mistakes.
- **Patch-based response:** Instead of replacing the whole buffer, the backend returns **diffs** (`patch_ops`). The user sees exactly what will change and can accept/reject per hunk. This avoids “AI overwrote my code” and supports incremental, reviewable edits (see `PATCH_MODE_IMPLEMENTATION.md`).
- **Conversation windowing:** Keeps context size bounded and prioritizes recent turns; avoids blowing the context window and keeps prompts cheaper.
- **Routing without an LLM:** Decisions like “do we need KB?” or “do we need web search?” are made with regex and set lookups. Saves tokens and latency and keeps behavior predictable.
- **Interaction logging and feedback:** Every request is stored; feedback (accepted/partial/rejected) drives usage and success stats for functions, presets, and recipes. Supports future improvements (e.g. ranking, A/B tests).

### 7.2 Frontend

- **Sidebar instead of inline chat:** Keeps the REPL and the copilot visually separate; the user always sees their code and the conversation side by side.
- **Streaming:** NDJSON stream gives quick status updates (“Loading relevant Strudel reference docs”, “Planning next moves”) and a single `final` payload. Better perceived performance and transparency.
- **Editor–sidebar contract:** The editor exposes `setPatchReview`, `acceptPatchHunk`, `rejectPatchHunk`, `clearPatchReview` and optionally emits `PATCH_ACTION_EVENT`. The sidebar stays agnostic of the exact editor implementation as long as this contract is fulfilled.
- **Base-code check:** Prevents applying patches when the document has changed since the response was generated, avoiding silent corruption.

### 7.3 System Design Summary

| Concern            | Choice                                      | Why                                                                 |
|--------------------|---------------------------------------------|---------------------------------------------------------------------|
| API                | REST + NDJSON stream                        | Simple, debuggable, works with fetch/EventSource-style consumption.  |
| Validation         | Multi-layer (forbidden, names, presets, args)| Catch as many invalid outputs as possible before showing to user.   |
| Edits              | Patches (hunks) not full replacement        | Safer, reviewable, minimal diffs.                                   |
| RAG                | Chroma (vectors) + SQLite (data)            | Semantic search + single source of truth and analytics.             |
| Repair             | Second LLM call with error + targeted docs  | Fix validation failures without complex multi-step graphs.          |
| Routing            | Heuristics (regex, sets)                    | No extra LLM call; predictable and fast.                            |

---

## 8. Key files (cheat sheet)

| Layer    | Path / file                                       | Role |
|----------|----------------------------------------------------|------|
| API      | `backend/main.py` → `backend/api/app.py`          | FastAPI app, CORS; `/api/copilot/chat`, `/chat/stream`, feedback. |
| Pipeline | `backend/copilot/orchestrator.py`                  | Orchestration: window, route, RAG, generate, validate, repair, patch, log. |
| LLM      | `backend/core/generation.py`                       | OpenAI Responses API, parsing, streaming, repair. |
| Prompts  | `backend/core/prompts.py`                         | System prompt, user message builder, static cache. |
| Context  | `backend/core/context_window.py`                   | Conversation history windowing. |
| RAG      | `backend/rag/retrieval.py`                        | Context bundles, preset/function/recipe retrieval. |
| Vectors  | `backend/rag/vector_store.py`                     | Chroma, embeddings, search. |
| Relations| `backend/rag/relationship_utils.py`               | Function–function relationships from recipe co-occurrence. |
| Routing  | `backend/core/routing.py`                         | `should_prefetch_kb`, `should_enable_web_search`, sound/effect detection. |
| Patches  | `backend/patching/patch_utils.py`                 | `build_patch_operations`, `summarize_patch_operations`. |
| Data     | `backend/db/models.py`, `session.py`, `init_db.py`| SQLAlchemy models (Function, Preset, Recipe, AIInteraction); DB creation. |
| Validation | `backend/copilot/validation.py`                    | Strudel/sound/args validation. |
| Interactions | `backend/copilot/interactions.py`                | Request logging, feedback recording. |
| Schemas  | `backend/core/schemas.py`                         | ChatRequest, ChatResponse, PatchOperation, StrudelCodeOut, etc. |
| Scripts  | `backend/scripts/import_data.py`, `indexing.py`   | KB import and vector-store indexing. |
| Frontend | `website/src/repl/components/copilot/`             | AICopilotSidebar, CopilotMessageList, CopilotInput, CopilotThinkingIndicator, copilotShared. |
| Docs     | Root `README.md`, `backend/README.md`             | Setup, run, troubleshooting; backend layout, RAG, patch mode. |

---

## 9. Optional setup (RAG / knowledge base)

For the copilot to use the Strudel function reference and validation (from project root, venv activated):

1. Create DB: `python -m backend.db.init_db`
2. Import data: `python -m backend.scripts.import_data` (expects `doc.json` at project root; generate with `pnpm run jsdoc-json`)
3. Index: `python -m backend.scripts.indexing` (builds Chroma from DB; requires `OPENAI_API_KEY`). Use `--force` to rebuild.

Without this, the backend still runs, but RAG and function/preset validation are limited or empty. See root `README.md` (Getting started) and `backend/README.md` for details.

---

## 10. Summary

- **App:** Strudel REPL fork + AI Copilot sidebar for natural-language pattern editing with reviewable patches.  
- **Strudel:** Browser-based live-coding music environment (strudel.cc).  
- **Backend:** FastAPI + OpenAI + SQLite + Chroma; generate → validate → repair → patch; strict Strudel-only validation; interaction logging and feedback.  
- **Frontend:** React sidebar; NDJSON streaming; per-hunk diff and Accept/Reject in chat and editor; base-code guard and editor–sidebar contract.  
- **Why:** Safe, minimal edits; RAG for accuracy; single-call fast path with repair fallback; clear separation between frontend and AI backend for maintainability and reuse.

This document and the root `README.md` (setup, running, troubleshooting) together give a full picture for a project presentation.
