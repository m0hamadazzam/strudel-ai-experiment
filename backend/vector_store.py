"""
Vector store setup for RAG (Retrieval Augmented Generation).

This module handles:
- Embedding model initialization
- Vector store creation and management
- Document storage and retrieval
"""

import os
from pathlib import Path
from typing import List, Optional, Tuple

from dotenv import load_dotenv
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

backend_dir = Path(__file__).parent
load_dotenv(backend_dir / ".env")

# Embedding model configuration
EMBEDDING_MODEL = "text-embedding-3-small"  # Cost-effective, good quality
EMBEDDING_DIMENSION = 1536  # For text-embedding-3-small

# Vector store configuration
VECTOR_STORE_DIR = "chroma_db"
COLLECTION_NAME = "strudel_knowledge_base"


def get_embeddings() -> OpenAIEmbeddings:
    """Initialize and return the OpenAI embeddings model."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set in environment")

    return OpenAIEmbeddings(
        model=EMBEDDING_MODEL,
        openai_api_key=api_key,
    )


def get_vector_store(embeddings: Optional[OpenAIEmbeddings] = None) -> Chroma:
    """
    Get or create the Chroma vector store.

    Args:
        embeddings: Optional embeddings model. If None, will create one.

    Returns:
        Chroma vector store instance
    """
    if embeddings is None:
        embeddings = get_embeddings()

    persist_directory = backend_dir / VECTOR_STORE_DIR

    # Create vector store with persistence
    vector_store = Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=str(persist_directory),
    )

    return vector_store


def add_documents_to_vector_store(
    documents: List[Document],
    vector_store: Optional[Chroma] = None,
    ids: Optional[List[str]] = None,
) -> List[str]:
    """
    Add documents to the vector store.

    This function is idempotent when stable IDs are provided:
    - Existing documents with those IDs are deleted first
    - Then the new documents are added with the same IDs

    Args:
        documents: List of Document objects to add.
        vector_store: Optional vector store instance. If None, will create one.
        ids: Optional list of stable document IDs. If provided, must be the
            same length as ``documents``.

    Returns:
        List of document IDs that were added.
    """
    if vector_store is None:
        vector_store = get_vector_store()

    if ids is not None:
        if len(ids) != len(documents):
            raise ValueError("Length of ids must match length of documents")

        # Best-effort delete of existing documents with these IDs to emulate upsert.
        # Chroma's LangChain wrapper supports delete by IDs across versions.
        try:
            # delete() is tolerant of unknown IDs.
            vector_store.delete(ids=ids)  # type: ignore[call-arg]
        except Exception:
            # If delete is not supported in a particular version, fail
            # gracefully by continuing without deletion. This may allow
            # duplicates but preserves backward compatibility.
            pass

        document_ids = vector_store.add_documents(documents, ids=ids)
    else:
        document_ids = vector_store.add_documents(documents)

    # Persist the vector store
    vector_store.persist()

    return document_ids


def search_vector_store(
    query: str,
    k: int = 5,
    filter_dict: Optional[dict] = None,
    vector_store: Optional[Chroma] = None,
) -> List[Document]:
    """
    Search the vector store for similar documents.

    Args:
        query: Search query string.
        k: Number of results to return (default: 5).
        filter_dict: Optional metadata filters.
        vector_store: Optional vector store instance. If None, will create one.

    Returns:
        List of Document objects sorted by relevance.
    """
    if vector_store is None:
        vector_store = get_vector_store()

    results = vector_store.similarity_search(
        query,
        k=k,
        filter=filter_dict,
    )

    return results


def search_vector_store_with_scores(
    query: str,
    k: int = 5,
    filter_dict: Optional[dict] = None,
    vector_store: Optional[Chroma] = None,
    score_threshold: Optional[float] = None,
) -> List[Tuple[Document, float]]:
    """
    Search the vector store and return documents with their similarity scores.

    This wraps ``similarity_search_with_score`` and optionally filters out
    low-relevance results using ``score_threshold``.

    Note: ``similarity_search_with_score`` typically returns a distance
    (lower is better). ``score_threshold`` is therefore treated as a
    *maximum* acceptable distance.

    Args:
        query: Search query string.
        k: Maximum number of results to return.
        filter_dict: Optional metadata filters.
        vector_store: Optional vector store instance. If None, will create one.
        score_threshold: Optional maximum distance threshold. Results with
            distance greater than this value are discarded.

    Returns:
        List of (Document, score) tuples.
    """
    if vector_store is None:
        vector_store = get_vector_store()

    results: List[Tuple[Document, float]] = vector_store.similarity_search_with_score(  # type: ignore[attr-defined]
        query,
        k=k,
        filter=filter_dict,
    )

    if score_threshold is None:
        return results

    filtered: List[Tuple[Document, float]] = [
        (doc, score) for doc, score in results if score <= score_threshold
    ]
    return filtered
