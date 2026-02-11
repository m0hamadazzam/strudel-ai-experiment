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

The RAG system is now integrated into `copilot.py`. When you make a request:

1. The system retrieves relevant context from the vector store
2. Enhances the system prompt with this context
3. Generates code using the enhanced prompt

## How It Works

### Retrieval Process

When a user makes a query:

1. **Semantic Search**: The query is embedded and searched against the vector store
2. **Function Name Extraction**: The system also looks for specific function names mentioned in the query
3. **Context Assembly**: Relevant functions, recipes, and presets are formatted into context
4. **Prompt Enhancement**: The context is injected into the system prompt

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

In `backend/copilot.py`, you can adjust:
- `k=5`: Number of results to retrieve (default: 5)
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
retrieve_relevant_context()  →  Vector Store Search
    ↓
extract_function_names()     →  Direct DB Lookup
    ↓
build_system_prompt(context)  →  Enhanced Prompt
    ↓
OpenAI API (gpt-5.1-codex-mini)
    ↓
Generated Code
```

## Files

- `vector_store.py`: Vector store initialization and management
- `indexing.py`: Script to index knowledge base into vector store
- `retrieval.py`: Functions to retrieve and format context
- `prompts.py`: Dynamic prompt building with context injection
- `copilot.py`: Main generation function with RAG integration
