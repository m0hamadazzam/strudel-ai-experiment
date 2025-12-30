from datetime import datetime
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    Float,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from pathlib import Path

Base = declarative_base()


class Function(Base):
    __tablename__ = "functions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    longname = Column(String(200))
    description = Column(Text)
    category = Column(String(50))
    kind = Column(String(50))
    scope = Column(String(50))
    synonyms = Column(Text)  # JSON array stored as text
    examples = Column(Text)  # JSON array stored as text
    params = Column(Text)  # JSON stored as text
    usage_count = Column(Integer, default=0)
    success_rate = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    relationships = relationship(
        "FunctionRelationship",
        foreign_keys="FunctionRelationship.function_id",
        back_populates="function",
    )


class FunctionRelationship(Base):
    __tablename__ = "function_relationships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    function_id = Column(Integer, ForeignKey("functions.id"), nullable=False)
    related_function_id = Column(Integer, ForeignKey("functions.id"), nullable=False)
    relationship_type = Column(String(50))
    strength = Column(Float, default=1.0)

    function = relationship("Function", foreign_keys=[function_id], back_populates="relationships")


class Preset(Base):
    __tablename__ = "presets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    type = Column(String(50))
    description = Column(Text)
    code_example = Column(Text)
    category = Column(String(50))
    tags = Column(Text)  # JSON array stored as text
    usage_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Recipe(Base):
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    code = Column(Text, nullable=False)
    category = Column(String(50))
    difficulty = Column(String(20))
    tags = Column(Text)  # JSON array stored as text
    related_functions = Column(Text)  # JSON array of function IDs
    usage_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AIContextCache(Base):
    __tablename__ = "ai_context_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query_hash = Column(String(64), unique=True, nullable=False)
    relevant_functions = Column(Text)  # JSON array
    relevant_recipes = Column(Text)  # JSON array
    context_text = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)


class AIInteraction(Base):
    __tablename__ = "ai_interactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_query = Column(Text, nullable=False)
    generated_code = Column(Text)
    applied = Column(Integer, default=0)  # SQLite uses INTEGER for boolean
    user_feedback = Column(String(20))
    functions_used = Column(Text)  # JSON array
    response_time_ms = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


# Database setup
def get_database_path():
    backend_dir = Path(__file__).parent
    return backend_dir / "strudel_kb.db"


def get_engine():
    db_path = get_database_path()
    return create_engine(f"sqlite:///{db_path}", echo=False)


def get_session():
    engine = get_engine()
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def init_database():
    engine = get_engine()
    Base.metadata.create_all(engine)

