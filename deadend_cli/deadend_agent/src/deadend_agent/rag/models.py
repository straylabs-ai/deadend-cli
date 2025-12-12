# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Database models for the retrieval-augmented generation (RAG) system.

This module defines SQLAlchemy models for storing code chunks, knowledge base
entries, and their vector embeddings in the PostgreSQL database with pgvector
extension for semantic search capabilities.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector


Base = declarative_base()

class CodeChunk(Base):
    """
    Model for storing code chunks with their embeddings.
    """
    __tablename__ = 'code_chunks'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    file_path = Column(String(500), nullable=False)
    # function_name = Column(String(200), nullable=True)
    # class_name = Column(String(200), nullable=True)
    code_content = Column(Text, nullable=False)
    language = Column(String(50), nullable=False)
    # start_line = Column(Integer, nullable=True)
    # end_line = Column(Integer, nullable=True)
    embedding = Column(Vector(4096), nullable=False)
    # Metadata
    created_at = Column(DateTime, default=datetime.now())
    updated_at = Column(DateTime, default=datetime.now(), onupdate=datetime.now())

    def __repr__(self):
        return f"<CodeChunk(id={self.id}, file_path='{self.file_path}')>"

class CodebaseChunk(Base):
    """
    Table model for codebase indexing 
    """

    __tablename__ = 'codebase_chunks'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_name = Column(String(500), nullable=False)
    file_path = Column(String(500), nullable=False)
    function_name = Column(String(200), nullable=True)
    class_name = Column(String(200), nullable=True)
    struct_name = Column(String(200), nullable=True)
    language = Column(String(50), nullable=False)
    code_content = Column(Text, nullable=False)
    embedding = Column(Vector(4096), nullable=False)
    # metadata
    created_at = Column(DateTime, default=datetime.now())
    updated_at = Column(DateTime, default=datetime.now(), onupdate=datetime.now())

    def __repr__(self):
        return f"<CodebaseChunks(id={self.id}, file_path='{self.file_path}')>"

class KnowledgeBase(Base):
    """
    DB Model for storing file chunks for knowledge 
    with their embeddings.  
    The files supported should be in Markdown.

    """
    __tablename__ = 'knowledge_base'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_path = Column(String(500), nullable=False)
    content_metadata = Column(Text, nullable=False)
    content  = Column(Text, nullable=False)
    embedding = Column(Vector(4096), nullable=False)
    # metadata
    created_at = Column(DateTime, default=datetime.now())
    updated_at = Column(DateTime, default=datetime.now(), onupdate=datetime.now())

    def __repr__(self):
        return f"<KnowledgeBase(id={self.id}, file_path='{self.file_path}')>"
