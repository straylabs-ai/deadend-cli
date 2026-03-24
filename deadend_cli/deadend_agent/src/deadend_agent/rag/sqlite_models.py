# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""SQLite-compatible database models for the RAG system.

These models store code chunks and knowledge base entries with embeddings
serialized as raw bytes (numpy float32 arrays via .tobytes()). Each .db
file represents a single (agent, target) session — no session_id column.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, LargeBinary
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _new_uuid() -> str:
    return str(uuid.uuid4())


class CodeChunkSqlite(Base):
    """Code chunk with embedding stored as a BLOB (numpy float32 bytes)."""

    __tablename__ = "code_chunks"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    file_path = Column(String(500), nullable=False)
    code_content = Column(Text, nullable=False)
    language = Column(String(50), nullable=False)
    embedding = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<CodeChunkSqlite(id={self.id}, file_path='{self.file_path}')>"


class KnowledgeBaseSqlite(Base):
    """Knowledge base chunk with embedding stored as a BLOB."""

    __tablename__ = "knowledge_base"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    file_path = Column(String(500), nullable=False)
    content_metadata = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<KnowledgeBaseSqlite(id={self.id}, file_path='{self.file_path}')>"


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def serialize_embedding(vec: list[float]) -> bytes:
    """Convert a list of floats to raw bytes (float32)."""
    import numpy as np
    return np.array(vec, dtype=np.float32).tobytes()


def deserialize_embedding(blob: bytes) -> list[float]:
    """Convert raw bytes back to a list of floats."""
    import numpy as np
    return np.frombuffer(blob, dtype=np.float32).tolist()
