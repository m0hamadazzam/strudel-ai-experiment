#!/usr/bin/env python3
"""
Initialize the SQLite database for Strudel AI Copilot knowledge base.

This script creates the database file and all necessary tables.
Run this once to set up the database before using the AI copilot.
"""

from .session import get_database_path, init_database


def main():
    db_path = get_database_path()

    if db_path.exists():
        print(f"Database already exists at {db_path}")
        response = input(
            "Do you want to recreate it? This will delete all data. (yes/no): "
        )
        if response.lower() != "yes":
            print("Aborted.")
            return
        db_path.unlink()
        print("Deleted existing database.")

    print(f"Creating database at {db_path}...")
    init_database()
    print("Database initialized successfully!")
    print(
        "Tables created: functions, function_relationships, presets, recipes, ai_interactions"
    )


if __name__ == "__main__":
    main()
