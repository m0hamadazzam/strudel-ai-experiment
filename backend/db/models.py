from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

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

    __table_args__ = (
        Index("idx_functions_category", "category"),
        Index("idx_functions_name", "name"),
        Index("idx_functions_usage", "usage_count"),
    )


class FunctionRelationship(Base):
    __tablename__ = "function_relationships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    function_id = Column(Integer, ForeignKey("functions.id"), nullable=False)
    related_function_id = Column(Integer, ForeignKey("functions.id"), nullable=False)
    relationship_type = Column(String(50))
    strength = Column(Float, default=1.0)

    function = relationship(
        "Function", foreign_keys=[function_id], back_populates="relationships"
    )


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

    __table_args__ = (Index("idx_recipes_category", "category"),)


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

    __table_args__ = (Index("idx_ai_interactions_created", "created_at"),)
