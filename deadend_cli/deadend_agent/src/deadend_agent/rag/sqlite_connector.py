# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""SQLite-backed RAG connector using aiosqlite + numpy cosine similarity.

Each ``.db`` file represents a single (agent, target) session.  There is no
``session_id`` column — the file *is* the session.  Embeddings are stored as
raw ``float32`` byte blobs and similarity search is done in-process with
numpy (brute-force cosine distance), which is fast enough for the expected
scale of a few thousand vectors per target.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

import numpy as np
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from deadend_agent.logging import get_module_logger

from .sqlite_models import (
    Base,
    CodeChunkSqlite,
    KnowledgeBaseSqlite,
    deserialize_embedding,
    serialize_embedding,
)

logger = get_module_logger(__name__)


class SqliteRagConnector:
    """RAG storage backed by a single SQLite database file."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            echo=False,
        )
        self.async_session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def initialize_database(self) -> None:
        """Create tables if they don't exist."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Enable WAL mode for better concurrent read performance
            await conn.execute(text("PRAGMA journal_mode=WAL"))

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.async_session() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    # ------------------------------------------------------------------
    # Code Chunks
    # ------------------------------------------------------------------

    async def batch_insert_code_chunks(
        self, code_chunks_data: List[Dict[str, Any]]
    ) -> List[CodeChunkSqlite]:
        """Insert multiple code chunks. Ignores ``session_id`` if present."""
        async with self.get_session() as session:
            chunks: list[CodeChunkSqlite] = []
            for data in code_chunks_data:
                # Strip fields that don't exist on the SQLite model
                cleaned = {k: v for k, v in data.items() if k != "session_id"}
                # Serialize embedding list → bytes
                if "embedding" in cleaned and isinstance(cleaned["embedding"], list):
                    cleaned["embedding"] = serialize_embedding(cleaned["embedding"])
                chunk = CodeChunkSqlite(**cleaned)
                chunks.append(chunk)

            session.add_all(chunks)
            await session.commit()
            for chunk in chunks:
                await session.refresh(chunk)
            return chunks

    async def delete_code_chunks_for_files(
        self, files: List[Dict[str, str]]
    ) -> int:
        """Delete code chunks for specific files (by file_path and language)."""
        if not files:
            return 0
        async with self.get_session() as session:
            total_deleted = 0
            for file_ref in files:
                stmt = delete(CodeChunkSqlite).where(
                    CodeChunkSqlite.file_path == file_ref.get("file_path", ""),
                    CodeChunkSqlite.language == file_ref.get("language", ""),
                )
                result = await session.execute(stmt)
                total_deleted += result.rowcount or 0
            await session.commit()
            logger.info(
                "Deleted %d code chunks (files=%d)",
                total_deleted,
                len(files),
            )
            return total_deleted

    async def similarity_search_code_chunk(
        self,
        query_embedding: List[float],
        vector_dim: int,
        limit: int = 10,
        language: Optional[str] = None,
        similarity_threshold: Optional[float] = None,
    ) -> List[tuple]:
        """Cosine-similarity search over code chunks (numpy brute-force).

        Returns a list of ``(CodeChunkSqlite, similarity_score)`` tuples
        ordered by descending similarity.
        """
        async with self.get_session() as session:
            query = select(CodeChunkSqlite)
            if language:
                query = query.where(CodeChunkSqlite.language == language)
            result = await session.execute(query)
            all_chunks: list[CodeChunkSqlite] = list(result.scalars().all())

        if not all_chunks:
            return []

        # Build matrix of stored embeddings
        query_vec = np.array(query_embedding, dtype=np.float32)
        embeddings = np.array(
            [np.frombuffer(c.embedding, dtype=np.float32) for c in all_chunks],
            dtype=np.float32,
        )

        # Filter by vector_dim — only compare chunks whose embedding
        # dimensionality matches the query
        valid_mask = np.array([e.shape[0] == vector_dim for e in embeddings])
        if not valid_mask.any():
            return []

        valid_indices = np.where(valid_mask)[0]
        valid_embeddings = embeddings[valid_mask]

        # Cosine similarity
        norms = np.linalg.norm(valid_embeddings, axis=1)
        query_norm = np.linalg.norm(query_vec)
        # Avoid division by zero
        safe_denom = norms * query_norm
        safe_denom[safe_denom == 0] = 1e-10
        similarities = valid_embeddings @ query_vec / safe_denom

        # Apply threshold
        if similarity_threshold is not None:
            keep = similarities >= similarity_threshold
            valid_indices = valid_indices[keep]
            similarities = similarities[keep]

        # Sort descending and take top-k
        top_k_idx = np.argsort(-similarities)[:limit]

        results: list[tuple] = []
        for idx in top_k_idx:
            chunk = all_chunks[valid_indices[idx]]
            score = float(similarities[idx])
            results.append((chunk, score))
        return results

    # ------------------------------------------------------------------
    # Knowledge Base
    # ------------------------------------------------------------------

    async def batch_insert_kb_chunks(
        self, knowledge_chunks_data: List[Dict[str, Any]]
    ) -> List[KnowledgeBaseSqlite]:
        async with self.get_session() as session:
            chunks: list[KnowledgeBaseSqlite] = []
            for data in knowledge_chunks_data:
                cleaned = dict(data)
                if "embedding" in cleaned and isinstance(cleaned["embedding"], list):
                    cleaned["embedding"] = serialize_embedding(cleaned["embedding"])
                chunk = KnowledgeBaseSqlite(**cleaned)
                chunks.append(chunk)
            session.add_all(chunks)
            await session.commit()
            for chunk in chunks:
                await session.refresh(chunk)
            return chunks

    async def similarity_search_knowledge_base(
        self,
        query_embedding: List[float],
        limit: int = 10,
        similarity_threshold: Optional[float] = None,
    ) -> List[tuple]:
        """Cosine-similarity search over knowledge base chunks."""
        async with self.get_session() as session:
            result = await session.execute(select(KnowledgeBaseSqlite))
            all_chunks: list[KnowledgeBaseSqlite] = list(result.scalars().all())

        if not all_chunks:
            return []

        query_vec = np.array(query_embedding, dtype=np.float32)
        embeddings = np.array(
            [np.frombuffer(c.embedding, dtype=np.float32) for c in all_chunks],
            dtype=np.float32,
        )

        norms = np.linalg.norm(embeddings, axis=1)
        query_norm = np.linalg.norm(query_vec)
        safe_denom = norms * query_norm
        safe_denom[safe_denom == 0] = 1e-10
        similarities = embeddings @ query_vec / safe_denom

        if similarity_threshold is not None:
            keep = similarities >= similarity_threshold
            indices = np.where(keep)[0]
            similarities = similarities[keep]
        else:
            indices = np.arange(len(all_chunks))

        top_k_idx = np.argsort(-similarities)[:limit]

        results: list[tuple] = []
        for idx in top_k_idx:
            chunk = all_chunks[indices[idx]]
            score = float(similarities[idx])
            results.append((chunk, score))
        return results

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self.engine.dispose()
