# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Pydantic schemas for web resource data structures.

This module defines Pydantic models for web resource chunks, including
metadata, content, and processing information for security research
and analysis workflows.
"""

from dataclasses import dataclass
from typing import List
from pydantic import BaseModel
from datetime import datetime
import uuid

from deadend_agent.models.registry import EmbedderClient


@dataclass
class CodeSection:
    """Represents a code section with metadata and embeddings.

    Attributes:
        url_path: URL or file path where the code section is located.
        title: Descriptive title for the code section.
        content: Dictionary containing the actual code content.
        embeddings: Vector embeddings for semantic search.
    """
    url_path: str
    title: str
    content: dict[int, str] | None
    embeddings: List[float] | None

    def get_embedding_content(self) -> str:
        """Get content formatted for embedding generation.

        This method implements the Embeddable protocol by providing
        a standardized way to get embedding content.
        """
        return '\n\n'.join(
            (f'url_path: {self.url_path}', f'title: {self.title}', str(self.content))
        )

    async def embed_content(self, embedder_client: EmbedderClient):
        """Generate embeddings for the code section content."""
        try:
            batch_embeddings = await embedder_client.batch_embed(input_texts=[str(self.content)])
            self.embeddings = batch_embeddings[0]['embedding']
        except Exception as e:
            self.embeddings = None

class WebResourceChunk(BaseModel):
    """
    WebResource Chunks schema 
    defines the resources gathered from the target. 
    """
    file_path : str
    code_content: str
    language: str
    embedding: list[float]
    created_at: datetime
    updated_at: datetime

class WebResourceChunkPatch(BaseModel):
    file_path : str | None
    code_content: str| None
    language: str | None
    embedding: list[float] | None
    updated_at: datetime

class WebResourceChunkDelete(BaseModel):
    id: uuid.UUID


class CodebaseChunk(BaseModel):
    """
    Codebase Chunks schema
    """
    project_name: str
    file_path: str
    function_name: str | None
    class_name: str | None
    struct_name: str | None
    language: str
    code_content: str
    embedding: list[float]
    created_at: datetime
    updated_at: datetime

class CodeBaseChunkPatch(BaseModel):
    file_path: str | None
    function_name: str | None
    class_name: str | None
    struct_name: str | None
    language: str | None
    code_content: str | None
    embedding: list[float] | None
    updated_at: datetime

class CodeBaseChunkDelete(BaseModel):
    id: uuid.UUID


class KnowledgeBase(BaseModel):
    """
    Knowledge Base chunks schema
    """
    file_path: str
    content: str
    embedding: list[float]
    created_at: datetime
    updated_at: datetime

class KnowledgeBasePatch(BaseModel):
    """
    Knowledge Base chunks schema
    """
    file_path: str | None
    content: str | None
    embedding: list[float] | None
    updated_at: datetime

class KnowledgeBaseDelete(BaseModel):
    id: uuid.UUID