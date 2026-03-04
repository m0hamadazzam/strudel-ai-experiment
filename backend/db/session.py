from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base


def get_database_path():
    """Return the absolute path to the SQLite knowledge-base database file."""
    backend_dir = Path(__file__).resolve().parent.parent
    return backend_dir / "strudel_kb.db"


_engine = None
_session_factory = None


def get_engine():
    """Return a lazily-initialized SQLAlchemy Engine for the KB database."""
    global _engine
    if _engine is None:
        db_path = get_database_path()
        _engine = create_engine(f"sqlite:///{db_path}", echo=False)
    return _engine


def get_session():
    """Return a new SQLAlchemy Session for the KB database."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            autocommit=False, autoflush=False, bind=get_engine()
        )
    return _session_factory()


def init_database():
    """Create all database tables if they do not already exist."""
    Base.metadata.create_all(get_engine())
