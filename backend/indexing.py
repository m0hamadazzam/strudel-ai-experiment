#!/usr/bin/env python3
"""
Index Strudel knowledge base into vector store for RAG.

This script:
1. Loads functions, recipes, and presets from SQLite database
2. Creates document chunks with metadata
3. Generates embeddings and stores in Chroma vector store
"""

import json
from pathlib import Path
from typing import List

from langchain_core.documents import Document

from .database import Function, Preset, Recipe, get_session
from .vector_store import add_documents_to_vector_store, get_vector_store


def create_function_document(func: Function) -> Document:
    """
    Create a Document from a Function database record.

    Args:
        func: Function database object

    Returns:
        Document with function information and metadata
    """
    # Build the document content
    content_parts = []

    if func.description:
        content_parts.append(f"Description: {func.description}")

    # Add parameters if available
    if func.params and func.params != "{}" and func.params != "[]":
        try:
            params = json.loads(func.params)
            if params:
                if isinstance(params, dict):
                    params_str = ", ".join([f"{k}: {v}" for k, v in params.items()])
                else:
                    params_str = str(params)
                content_parts.append(f"Parameters: {params_str}")
        except json.JSONDecodeError:
            pass

    # Add examples if available
    if func.examples and func.examples != "[]":
        try:
            examples = json.loads(func.examples)
            if examples:
                examples_str = "\n".join(
                    [f"  - {ex}" for ex in examples[:3]]
                )  # Limit to 3 examples
                content_parts.append(f"Examples:\n{examples_str}")
        except json.JSONDecodeError:
            pass

    # Add synonyms if available
    if func.synonyms and func.synonyms != "[]":
        try:
            synonyms = json.loads(func.synonyms)
            if synonyms:
                synonyms_str = ", ".join(synonyms)
                content_parts.append(f"Also known as: {synonyms_str}")
        except json.JSONDecodeError:
            pass

    content = f"Function: {func.name}\n" + "\n".join(content_parts)

    # Create metadata
    metadata = {
        "type": "function",
        "name": func.name,
        "category": func.category or "unknown",
        "kind": func.kind or "",
        "scope": func.scope or "",
        "function_id": func.id,
    }

    return Document(page_content=content, metadata=metadata)


def create_recipe_document(recipe: Recipe) -> Document:
    """
    Create a Document from a Recipe database record.

    Args:
        recipe: Recipe database object

    Returns:
        Document with recipe information and metadata
    """
    content_parts = []

    if recipe.description:
        content_parts.append(f"Description: {recipe.description}")

    if recipe.code:
        # Include code but truncate if too long
        code_preview = (
            recipe.code[:500] + "..." if len(recipe.code) > 500 else recipe.code
        )
        content_parts.append(f"Code example:\n{code_preview}")

    content = f"Recipe: {recipe.title}\n" + "\n".join(content_parts)

    metadata = {
        "type": "recipe",
        "title": recipe.title,
        "category": recipe.category or "unknown",
        "difficulty": recipe.difficulty or "unknown",
        "recipe_id": recipe.id,
    }

    return Document(page_content=content, metadata=metadata)


def create_preset_document(preset: Preset) -> Document:
    """
    Create a Document from a Preset database record.

    Args:
        preset: Preset database object

    Returns:
        Document with preset information and metadata
    """
    content_parts = []

    if preset.description:
        content_parts.append(f"Description: {preset.description}")

    if preset.code_example:
        code_preview = (
            preset.code_example[:300] + "..."
            if len(preset.code_example) > 300
            else preset.code_example
        )
        content_parts.append(f"Example: {code_preview}")

    content = f"Preset: {preset.name}\n" + "\n".join(content_parts)

    metadata = {
        "type": "preset",
        "name": preset.name,
        "preset_type": preset.type or "unknown",
        "category": preset.category or "unknown",
        "preset_id": preset.id,
    }

    return Document(page_content=content, metadata=metadata)


def index_knowledge_base(force_recreate: bool = False) -> dict:
    """
    Index all knowledge base content into the vector store.

    Args:
        force_recreate: If True, delete existing vector store and recreate

    Returns:
        Dictionary with indexing statistics
    """
    session = get_session()

    try:
        # Get vector store
        vector_store = get_vector_store()

        # If force_recreate, delete existing collection directory
        # so that a clean index can be built from the SQLite source of truth.
        if force_recreate:
            try:
                backend_dir = Path(__file__).parent
                persist_dir = backend_dir / "chroma_db"
                if persist_dir.exists():
                    import shutil

                    shutil.rmtree(persist_dir)
                    print("Deleted existing vector store.")
                    # Recreate a fresh vector store instance after deletion.
                    vector_store = get_vector_store()
            except Exception as e:
                print(f"Warning: Could not delete existing vector store: {e}")

        documents: List[Document] = []
        ids: List[str] = []

        # Index functions
        print("Loading functions from database...")
        functions = session.query(Function).all()
        print(f"Found {len(functions)} functions")

        for func in functions:
            doc = create_function_document(func)
            documents.append(doc)
            ids.append(f"function:{func.id}")

        # Index recipes
        print("Loading recipes from database...")
        recipes = session.query(Recipe).all()
        print(f"Found {len(recipes)} recipes")

        for recipe in recipes:
            doc = create_recipe_document(recipe)
            documents.append(doc)
            ids.append(f"recipe:{recipe.id}")

        # Index presets
        print("Loading presets from database...")
        presets = session.query(Preset).all()
        print(f"Found {len(presets)} presets")

        for preset in presets:
            doc = create_preset_document(preset)
            documents.append(doc)
            ids.append(f"preset:{preset.id}")

        # Add all documents to vector store with stable IDs (idempotent indexing)
        print(f"\nIndexing {len(documents)} documents into vector store...")
        document_ids = add_documents_to_vector_store(
            documents,
            vector_store=vector_store,
            ids=ids,
        )

        print(f"Successfully indexed {len(document_ids)} documents!")

        return {
            "functions": len(functions),
            "recipes": len(recipes),
            "presets": len(presets),
            "total_documents": len(documents),
            "indexed": len(document_ids),
        }

    except Exception as e:
        print(f"Error during indexing: {e}")
        raise
    finally:
        session.close()


def main():
    """Main function to run indexing."""
    import sys

    force_recreate = "--force" in sys.argv or "-f" in sys.argv

    if force_recreate:
        response = input(
            "This will delete the existing vector store. Continue? (yes/no): "
        )
        if response.lower() != "yes":
            print("Aborted.")
            return

    print("=== Strudel Knowledge Base Indexing ===\n")

    try:
        stats = index_knowledge_base(force_recreate=force_recreate)

        print("\n=== Indexing Summary ===")
        print(f"Functions indexed: {stats['functions']}")
        print(f"Recipes indexed: {stats['recipes']}")
        print(f"Presets indexed: {stats['presets']}")
        print(f"Total documents: {stats['total_documents']}")
        print(f"Successfully indexed: {stats['indexed']}")
        print("\nIndexing completed successfully!")

    except Exception as e:
        print(f"\nFatal error: {e}")
        raise


if __name__ == "__main__":
    main()
