# RAG (Retrieval Augmented Generation) Setup Guide

This guide explains how to set up and use the RAG system for the Strudel AI Copilot.

## Overview

The RAG system enhances the AI copilot by:
1. **Indexing** the knowledge base (functions, recipes, presets) into a vector store
2. **Retrieving** relevant context based on user queries
3. **Enhancing** prompts with retrieved context for more accurate code generation

## Setup Steps

### 1. Install Dependencies

Make sure you have all required packages:

```bash
pip install -r requirements.txt
```

This will install:
- LangChain and related packages
- ChromaDB (vector store)
- OpenAI SDK (already installed)

### 2. Ensure Knowledge Base is Populated

Make sure your SQLite database has been populated with functions:

```bash
# If not already done, import functions from doc.json
python -m backend.import_data
```

### 3. Index the Knowledge Base

Run the indexing script to create embeddings and populate the vector store:

```bash
# From project root
python -m backend.indexing

# Or to force recreate (deletes existing vector store)
python -m backend.indexing --force
```

This will:
- Load all functions, recipes, and presets from the SQLite database
- Generate embeddings using OpenAI's `text-embedding-3-small` model
- Store them in a ChromaDB vector store (saved in `backend/chroma_db/`)

**Note:** This requires `OPENAI_API_KEY` to be set in your environment.

### 4. Verify Setup

The RAG **agent** is integrated into `copilot.py`. When you make a request:

1. The **agent** (LLM) decides whether to search the knowledge base and with what query
2. If it calls the KB tool, the **retrieve** node runs and returns formatted context
3. The **generate_code** node builds the system prompt with that context and calls the LLM with structured output (`StrudelCodeOut`)
4. The copilot validates the code and returns `ChatResponse`

## How It Works

### RAG Agent (LangGraph)

When a user makes a query:

1. **Agent node**: The LLM receives the user message and a system prompt instructing it to call `search_strudel_knowledge_base` with a search query when the user asks for code. It may respond with a tool call (retrieve) or go straight to code generation.
2. **Retrieve node** (if the agent called the tool): Runs the KB tool, which calls `retrieve_relevant_context()` (vector search → hydrate from SQLite → format). The tool result is appended to the conversation.
3. **Generate_code node**: Reads the conversation (including any tool message with KB context), builds `build_system_prompt(kb_context=...)`, and calls the OpenAI API with structured output to produce `StrudelCodeOut` (code + explanation). Validation runs in `copilot.py` after the graph returns.

### Vector Store Location

The vector store is persisted in: `backend/chroma_db/`

You can delete this directory and re-run indexing to rebuild it.

## Configuration

### Embedding Model

Currently using: `text-embedding-3-small`

To change, edit `backend/vector_store.py`:
```python
EMBEDDING_MODEL = "text-embedding-3-small"  # or "text-embedding-3-large"
```

### Retrieval Parameters

In `backend/retrieval.py` (used by the KB tool), you can adjust:
- `k`: Number of vector results (default: 4)
- Context limits: Top 3 functions, top 2 recipes, top 2 presets

## Troubleshooting

### "Context retrieval failed" warning

This is normal if:
- Vector store hasn't been indexed yet
- OPENAI_API_KEY is not set
- Vector store files are corrupted

The system will gracefully degrade and work without context.

### Re-indexing

If you update the knowledge base (add new functions, recipes, etc.):

```bash
python -m backend.indexing --force
```

### Check Vector Store

To verify the vector store has data:

```python
from backend.vector_store import get_vector_store

vs = get_vector_store()
# Check collection count (if ChromaDB supports it)
results = vs.similarity_search("drum pattern", k=1)
print(f"Found {len(results)} results")
```

## Architecture

```
User Query
    ↓
Agent node (LLM + search_strudel_knowledge_base tool)
    ↓
tool_calls? → Yes → Retrieve node (KB tool → retrieve_relevant_context)
    ↓                    ↓
    No                   ↓
    ↓              generate_code node
    └──────────────────→ (build_system_prompt(kb_context) + structured output)
    ↓
StrudelCodeOut → Validate → ChatResponse
```

## Files

- `vector_store.py`: Vector store initialization and management
- `indexing.py`: Script to index knowledge base into vector store
- `retrieval.py`: Functions to retrieve and format context (used by the KB tool)
- `rag_agent.py`: LangGraph RAG agent (KB tool, agent/retrieve/generate_code nodes, compiled graph)
- `prompts.py`: Dynamic prompt building with KB context (used in generate_code node)
- `copilot.py`: Invokes the RAG graph, validates output, returns ChatResponse
