# Strudel AI Copilot – Architecture & Design

This document explains how the Strudel AI Copilot is created, designed, and how it works end-to-end.

---

## 1. Overview

The **Strudel AI Copilot** is an experimental AI sidebar for the browser-based Strudel REPL. It helps users write and edit **Strudel** (live-coding) JavaScript by:

- Taking a natural-language request (e.g. “add a drum beat”, “stack a melody on top”).
- Generating runnable Strudel code using an LLM, augmented with a **knowledge base** (RAG).
- Returning **minimal, reviewable patches** instead of overwriting the whole buffer, so users can accept or reject each change.

The system is split into:

- **Frontend**: Astro/React website with a chat-style sidebar and CodeMirror editor integration.
- **Backend**: FastAPI service that runs a **RAG agent** (LangGraph), validates output, and computes **patch operations** for the editor.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Frontend (Astro + React, localhost:4321)                                   │
│  ┌──────────────────────┐  ┌─────────────────────────────────────────────┐│
│  │  ReplEditor           │  │  AICopilotSidebar                             ││
│  │  ┌──────────────────┐ │  │  • Chat UI (messages, input, send)            ││
│  │  │ Code (CodeMirror) │ │  │  • Patch hunks: Accept / Reject (per hunk or  ││
│  │  │ + patchReview     │◄┼──┼──  all)                                       ││
│  │  │ extension         │ │  │  • Session token/usage display                ││
│  │  └──────────────────┘ │  │  • POST /api/copilot/chat (message, code)    ││
│  │  editorRef → Strudel  │  └───────────────────────────┬───────────────────┘│
│  │  Mirror (setPatchReview│                              │                    │
│  │  accept/rejectHunk)   │                              │                    │
│  └──────────────────────┘                              │                    │
└─────────────────────────────────────────────────────────┼────────────────────┘
                                                          │
                                                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Backend (FastAPI, localhost:8000)                                           │
│  POST /api/copilot/chat                                                       │
│       │                                                                      │
│       ▼                                                                      │
│  copilot.generate_code(request)                                              │
│       │                                                                      │
│       ├─► get_rag_graph().invoke(initial_state)                              │
│       │        │                                                             │
│       │        ├─► agent node   (LLM: decide search query → tool or skip)    │
│       │        ├─► retrieve     (ToolNode: search_strudel_knowledge_base)   │
│       │        └─► generate_code (system_prompt + KB context → structured    │
│       │                           output StrudelCodeOut)                    │
│       │                                                                      │
│       ├─► Validate code (forbidden patterns, KB-allowed names only)          │
│       ├─► build_patch_operations(current_code, new_code)                     │
│       └─► ChatResponse(code, explanation, patch_ops, patch_stats, usage)     │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. How the Copilot Is Created

### 3.1 Backend Setup

- **Framework**: FastAPI (`backend/main.py`).
- **Single chat endpoint**: `POST /api/copilot/chat` with body `{ message, current_code }`. It delegates to `generate_code` in `backend/copilot.py`.
- **Environment**: `OPENAI_API_KEY` in `backend/.env` is required. Optional: Langfuse keys for tracing.

### 3.2 RAG Agent (LangGraph)

The “brain” of the copilot is a **LangGraph** workflow in `backend/rag_agent.py`:

1. **State**: `RAGAgentState` with:
   - `messages` (reducer: `add_messages`) – conversation + tool results.
   - `parsed_output` – optional `StrudelCodeOut` (code + explanation).
   - `usage` – token counts.

2. **Nodes**:
   - **agent**: Chat model (e.g. `gpt-4o-mini`) with tool `search_strudel_knowledge_base`. It decides whether to call the KB with a search query or go straight to code generation.
   - **retrieve**: `ToolNode` that runs the KB tool → calls `retrieve_relevant_context()` (vector search + SQLite hydration).
   - **generate_code**: Reads user message and any tool message (KB context), builds `build_system_prompt(kb_context=...)`, then calls **OpenAI Responses API** with **structured output** (`StrudelCodeOut`). Optional web search is enabled for Strudel/TidalCycles examples.

3. **Graph edges**:
   - `START → agent`
   - `agent --(tool_calls?)--> retrieve` or `agent --> generate_code`
   - `retrieve → generate_code`
   - `generate_code → END`

4. **Singleton**: `get_rag_graph()` compiles the graph once and caches it for use from `copilot.py`.

### 3.3 Knowledge Base (RAG)

- **Source of truth**: SQLite (`backend/`), with tables for **functions**, **recipes**, **presets**.
- **Vector store**: ChromaDB in `backend/chroma_db/`, used only as a semantic index (returns document IDs).
- **Indexing**: `python -m backend.indexing` (and `--force` to rebuild) embeds KB content and fills Chroma. See `backend/RAG_SETUP.md`.
- **Retrieval** (`backend/retrieval.py`): `retrieve_relevant_context(query, k=4, ...)` does vector search, groups by type, hydrates full records from SQLite, applies caps (e.g. 3 functions, 2 recipes, 2 presets) and a character budget, then returns a formatted string for the prompt.
- **Query enhancement**: `extract_function_names_from_query()` detects known function names/synonyms in the user query and can boost those in retrieval.

### 3.4 Prompts

- **Agent** (`rag_agent.py`): System prompt tells the LLM to call `search_strudel_knowledge_base` with a short search query when the user asks for code; it must not generate code in this step.
- **Code generation** (`backend/prompts.py`): `build_system_prompt(kb_context="")`:
  - Injects “Strudel facts” (mini-notation, patterns, setcpm, etc.).
  - If `kb_context` is non-empty, adds a “Knowledge Base” section and instructs the model to use only APIs from KB or Strudel facts.
  - Enforces: code only in `code` field, no Node/browser APIs, minimal edits when `current_code` is provided, additive requests keep existing layers.

### 3.5 Schemas

- **Request**: `ChatRequest(message, current_code)`.
- **Response**: `ChatResponse(code, explanation, patch_ops, patch_stats, usage)`.
- **Structured output**: `StrudelCodeOut(code, explanation)` – what the LLM returns.
- **Patch**: `PatchOperation(op, start, end, old_text, new_text)` and `PatchStats(additions, deletions, operations)`.

---

## 4. How It Works End-to-End

### 4.1 User Sends a Message

1. User types in the **AICopilotSidebar** input and sends (or Enter).
2. Sidebar calls `getLiveCode()` from `context` (editor’s current code) and sends:
   - `POST http://localhost:8000/api/copilot/chat`
   - Body: `{ message: text, current_code: currentCode }`.

### 4.2 Backend: Generate and Validate

1. **copilot.py** `generate_code(request)`:
   - Builds user content: `current_code` + `message` (or just `message`).
   - Sets `initial_state = { messages: [HumanMessage(content=...)] }`.
   - Invokes `get_rag_graph().invoke(initial_state)` (optionally with Langfuse).
2. **RAG graph** runs:
   - **Agent** may call `search_strudel_knowledge_base(query)`; **retrieve** runs the tool and appends the result to `messages`.
   - **generate_code** builds the system prompt (with KB context if any), calls OpenAI with structured output, and returns `parsed_output` (and `usage`).
3. **copilot.py** then:
   - If `parsed_output` is missing → returns error response.
   - Validates generated code: forbidden patterns (e.g. `require(`, `import `) and **KB-allowed names only** for function/method calls (from `_get_allowed_function_names()`).
   - On validation failure → returns error and keeps `current_code`.
   - On success: computes `patch_ops = build_patch_operations(current_code, code)`, `patch_stats = summarize_patch_operations(patch_ops)`, aggregates usage (and optional Langfuse cost), logs the interaction to SQLite, and returns `ChatResponse(code, explanation, patch_ops, patch_stats, usage)`.

### 4.3 Patch Computation

- **patch_utils.py**: `build_patch_operations(base_code, target_code)` uses Python’s `SequenceMatcher` on **lines** to produce a list of `PatchOperation` (insert/delete/replace) with character offsets and `old_text`/`new_text`. So the frontend receives minimal diffs instead of only the full file.

### 4.4 Frontend: Display and Review

1. **AICopilotSidebar** receives the JSON response:
   - Appends an assistant message with `content` (explanation), `code`, `patch_ops`, `patch_stats`, `usage`.
   - Converts `patch_ops` to **hunks** (with `buildPatchHunks`): each hunk has `id`, `op`, `start`, `end`, `oldText`, `newText`, `status: 'pending'`.
2. If there are hunks, the sidebar calls **activatePatchMessage** → `context.editorRef.current.setPatchReview(pendingHunks)`.
3. **CodeMirror** (`packages/codemirror/patchReview.mjs` + `codemirror.mjs`):
   - **patchReviewExtension** stores hunks in a state field and builds decorations:
     - Red mark (`cm-aiPatchRemove`) for the range to be replaced/deleted.
     - Green widget block with new text and “Accept” / “Reject” buttons.
   - Toolbar widget at the top offers “Accept all” / “Reject all”.
4. User can:
   - **In the sidebar**: Click “Show in editor”, “Accept” / “Reject” per hunk, or “Accept all” / “Reject all”.
   - **In the editor**: Use the inline Accept/Reject on each hunk widget.
5. Accept/Reject in the editor dispatches a custom event `strudel-ai-patch-hunk-action`; the sidebar listens and updates hunk status so chat and editor stay in sync.
6. **Guard**: If the current editor code no longer matches the `baseCode` of the message, the sidebar refuses to activate that patch and notifies the user (code drifted).

### 4.5 Applying a Hunk

- **acceptPatchReviewHunk** (in `patchReview.mjs`): Checks that the document text in `[hunk.start, hunk.end]` still equals `hunk.oldText`; if so, dispatches a change that replaces that range with `hunk.newText` and marks the hunk as accepted. If not, it returns `false` (e.g. code drifted).
- **rejectPatchReviewHunk**: Just marks the hunk as rejected (no document change).

---

## 5. Design Decisions

| Area | Decision | Rationale |
|------|----------|------------|
| **Patch mode** | Return full `code` plus `patch_ops`; UI shows hunks and applies them only on user approval. | Avoids full-buffer overwrite; user sees exactly what will change and can accept/reject per hunk. |
| **RAG** | Agent decides whether and how to query KB; retrieve node returns formatted context; generate_code gets that in the system prompt. | Keeps generation grounded in Strudel API and examples. |
| **Validation** | Reject code that uses forbidden patterns or calls functions/methods not in the KB. | Ensures generated code stays within Strudel’s allowed surface. |
| **Structured output** | OpenAI Responses API with `StrudelCodeOut` (Pydantic). | Guarantees a clean `code` + `explanation` shape without asking the model to emit raw JSON in text. |
| **Two models** | Agent node: Chat Completions model (e.g. gpt-4o-mini). Code gen: Responses API model (e.g. gpt-5.1-codex-mini). | Tool-calling for RAG vs. structured code output have different API requirements. |
| **SQLite + Chroma** | SQLite = source of truth; Chroma = vector index; retrieval hydrates from SQLite. | Keeps canonical data in one place and uses vector search only for retrieval. |
| **Line-based patches** | `SequenceMatcher` on lines → character offsets. | Simple, deterministic, and good enough for typical edits; intra-line edits appear as line replacements. |

---

## 6. Key Files

| Layer | File | Role |
|-------|------|------|
| **API** | `backend/main.py` | FastAPI app, CORS, `POST /api/copilot/chat` → `generate_code`. |
| **Orchestration** | `backend/copilot.py` | Builds user content, invokes RAG graph, validates code, builds patches, logs interactions, returns `ChatResponse`. Optional Langfuse. |
| **RAG graph** | `backend/rag_agent.py` | LangGraph: agent → retrieve (tool) → generate_code; `get_rag_graph()`. |
| **Prompts** | `backend/prompts.py` | `build_system_prompt(kb_context)` for code generation. |
| **Retrieval** | `backend/retrieval.py` | `retrieve_relevant_context()`, `extract_function_names_from_query()`. |
| **Vector store** | `backend/vector_store.py` | ChromaDB and search. |
| **Patch logic** | `backend/patch_utils.py` | `build_patch_operations`, `summarize_patch_operations`, `apply_patch_operations`. |
| **Schemas** | `backend/schemas.py` | `ChatRequest`, `ChatResponse`, `PatchOperation`, `PatchStats`, `StrudelCodeOut`, `TokenUsage`. |
| **Sidebar UI** | `website/src/repl/components/AICopilotSidebar.jsx` | Chat, send, hunks UI, activate patch in editor, Accept/Reject, session usage. |
| **Editor integration** | `website/src/repl/components/ReplEditor.jsx` | Renders `Code` + `AICopilotSidebar`; passes `context` (includes `editorRef`). |
| **CodeMirror patch UI** | `packages/codemirror/patchReview.mjs` | State field, decorations, Accept/Reject widgets, `acceptPatchReviewHunk`, `rejectPatchReviewHunk`. |
| **CodeMirror wrapper** | `packages/codemirror/codemirror.mjs` | `StrudelMirror`: `setPatchReview`, `clearPatchReview`, `acceptPatchHunk`, `rejectPatchHunk` delegating to patchReview. |
| **Context** | `website/src/repl/useReplContext.jsx` | Creates `StrudelMirror`, sets `editorRef.current = editor`, provides `context` (e.g. `editorRef`, `activeCode`) to ReplEditor. |
| **Settings** | `website/src/settings.mjs` | `isAICopilotSidebarOpen`, `aiCopilotSidebarWidth`; used by sidebar. |

---

## 7. Optional Features

- **Langfuse**: If `LANGFUSE_SECRET_KEY` (and related env) is set, `copilot.py` and the generate_code node can send traces; cost can be read from Langfuse and attached to `TokenUsage`.
- **Session usage**: The sidebar sums `usage` (input/output tokens, estimated cost) per response and shows a session total.
- **Sidebar resize**: Dragging the left edge of the sidebar updates `aiCopilotSidebarWidth` in settings.

---

## 8. Running the Copilot

- From project root: `./start.sh` starts backend (uvicorn on 8000) and frontend (Astro on 4321).
- Open **http://localhost:4321**, ensure the AI Copilot sidebar is open (toggle if needed).
- Backend must have `OPENAI_API_KEY`; for RAG, run `python -m backend.init_db` and `python -m backend.indexing` as in `backend/RAG_SETUP.md` and `GETTING_STARTED.md`.

For more on RAG setup and indexing, see **backend/RAG_SETUP.md**. For patch-mode behavior and API contract, see **backend/PATCH_MODE_IMPLEMENTATION.md**.
