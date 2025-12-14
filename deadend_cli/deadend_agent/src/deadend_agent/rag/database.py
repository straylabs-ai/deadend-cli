# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Database connection and management for the security research framework.

This module provides database connectivity, schema management, and data
processing utilities for storing and retrieving security research data,
including code sections, embeddings, and analysis results.
"""
from typing import List
from dataclasses import dataclass
from contextlib import asynccontextmanager
import asyncio
import asyncpg
from deadend_agent.models.registry import EmbedderClient
from openai import AsyncOpenAI, BadRequestError
from rich.pretty import pprint
from typing_extensions import AsyncGenerator



# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
@asynccontextmanager
async def database_connect(
    create_db: bool = False
) -> AsyncGenerator[asyncpg.Pool, None]:
    """Create and manage database connection pool.
    
    Args:
        create_db: If True, creates the database if it doesn't exist.
        
    Yields:
        asyncpg.Pool: Database connection pool.
        
    Example:
        >>> async with database_connect() as pool:
        ...     async with pool.acquire() as conn:
        ...         result = await conn.fetchval("SELECT 1")
    """
    server_dsn, database = (
        'postgresql://postgres:postgres@localhost:54320',
        'code_indexer_db',
    )
    if create_db:
        conn = await asyncpg.connect(server_dsn)
        try:
            db_exists = await conn.fetchval(
                'SELECT 1 FROM pg_database WHERE datname = $1', database
            )
            if not db_exists:
                await conn.execute(f'CREATE DATABASE {database}')
        finally:
            await conn.close()

    pool = await asyncpg.create_pool(f'{server_dsn}/{database}')
    try:
        yield pool
    finally:
        await pool.close()

@dataclass
class RagDeps:
    """Dependencies for RAG (Retrieval-Augmented Generation) operations.
    
    Attributes:
        openai: OpenAI client for embedding generation.
        pool: Database connection pool for data storage and retrieval.
    """
    openai: AsyncOpenAI
    pool: asyncpg.Pool

@dataclass
class CodeSection:
    """Represents a code section with metadata and embeddings.
    
    Attributes:
        url_path: URL or file path where the code section is located.
        title: Descriptive title for the code section.
        content: Dictionary containing the actual code content.
        embeddings: Vector embeddings for semantic search (4096 dimensions).
    """
    url_path: str
    title: str
    content: dict[int, str] | None
    embeddings: List[float] | None


    def get_embedding_content(self) -> str:
        """Get content formatted for embedding generation.
        
        This method implements the Embeddable protocol by providing
        a standardized way to get embedding content.
        
        Returns:
            Formatted string suitable for embedding generation.
        """
        return '\n\n'.join(
            (f'url_path: {self.url_path}', f'title: {self.title}', str(self.content))
        )

    async def embed_content(
        self,
        embedder_client: EmbedderClient,
        # embedding_model: str
    ):
        """Generate embeddings for the code section content.
        
        Args:
            openai: OpenAI client instance for embedding generation.
            embedding_model: Name of the embedding model to use.
            
        Note:
            If embedding generation fails, embeddings will be set to None.
            The method handles BadRequestError exceptions gracefully.
        """
        try:
            # response = await openai.embeddings.create(
            #     input=str(self.content),
            #     model=embedding_model
            # )
            # assert len(response.data) == 1, (
            #     f'Expected 1 embedding, got {len(response.data)}, file : {self.title}'
            # )
            # self.embeddings = response.data[0].embedding
            self.embeddings = embedder_client.batch_embed(input=str(self.content))
        except BadRequestError as e:
            pprint(f"File {self.title} with content : {self.content} not embedded: {e}")
            self.embeddings = None

DB_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS code_sections (
    id serial PRIMARY KEY,
    url text NOT NULL,
    title text NOT NULL,
    content text NOT NULL,
    --  returns a vector of 4096 floats
    embedding vector(4096) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_code_sections_embedding ON code_sections USING hnsw (embedding vector_l2_ops);
"""


async def create_db():
    """Create database schema and tables.
    
    Creates the code_indexer_db database if it doesn't exist and sets up
    the required tables including the vector extension for embeddings.
    """
    async with database_connect(True) as pool:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(DB_SCHEMA)
