# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Pydantic schemas for web resource data structures.

This module defines Pydantic models for web resource chunks, including
metadata, content, and processing information for security research
and analysis workflows.
"""

from pydantic import BaseModel
from datetime import datetime
import uuid

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