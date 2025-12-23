# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Database operations for retrieval-augmented generation (RAG) system.

This module provides database connectivity and CRUD operations for storing
and retrieving code chunks, knowledge base entries, and embeddings used
in the security research framework's RAG system.
"""

import asyncio
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any, AsyncGenerator
from contextlib import asynccontextmanager
# import numpy as np
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text, select

from .models import Base, CodeChunk, KnowledgeBase

class RetrievalDatabaseConnector:
    """
    Retrieval database for codebases, webapp resources and documents
    """
    def __init__(self, database_url: str, pool_size: int = 20, max_overflow: int = 30):
        if database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

        self.engine = create_async_engine(
            database_url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            echo=False  # Set to True for SQL debugging
        )

        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

    async def initialize_database(self):
        """Initialize database tables and extensions."""
        async with self.engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Context manager for database sessions."""
        async with self.async_session() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def insert_knowledge_base_chunk(
        self,
        file_path: str,
        content_metadata: str,
        content: str,
        embedding: List[float]
    ) -> KnowledgeBase:
        """Insert Knowledge base chunk embeddings in the database."""
        async with self.get_session() as session:
            kb_chunk = KnowledgeBase(
                file_path=file_path,
                content_metadata=content_metadata,
                content=content,
                embedding=embedding
            )

            session.add(kb_chunk)
            await session.commit()
            await session.refresh(kb_chunk)
            return kb_chunk

    async def batch_insert_kb_chunks(
        self,
        knowledge_chunks_data: List[Dict[str, Any]]
    ) -> List[KnowledgeBase]:
        """
        Insert multiple Knowledge base chunks in a single transaction.
        Much faster than individual inserts.
        """
        async with self.get_session() as session:
            kb_chunks = []
            for data in knowledge_chunks_data:
                kb_chunk = KnowledgeBase(**data)
                kb_chunks.append(kb_chunk)

            session.add_all(kb_chunks)
            await session.commit()
            # Refresh all objects to get their IDs
            for chunk in kb_chunks:
                await session.refresh(chunk)
            return kb_chunks

    async def similarity_search_knowledge_base(self,
                               query_embedding: List[float],
                               limit: int = 10,
                               similarity_threshold: Optional[float] = None) -> List[tuple]:
        """
        Search for similar code chunks using vector similarity.
        """
        async with self.get_session() as session:
            # Build query with similarity calculation
            distance_expr = KnowledgeBase.embedding.cosine_distance(query_embedding) 
            query = select(
                KnowledgeBase,
                distance_expr.label('distance')
            )

            # Apply similarity threshold if specified
            if similarity_threshold:
                distance_threshold = 1 - similarity_threshold
                query = query.where(distance_expr <= distance_threshold)

            # Order by similarity and limit results
            query = query.order_by('distance').limit(limit)

            result = await session.execute(query)
            rows = result.all()

            # Convert distance back to similarity score
            return [(chunk, 1 - distance) for chunk, distance in rows]

    async def insert_code_chunk(self,
                               session_id: uuid.UUID,
                               file_path: str,
                               code_content: str,
                               embedding: List[float],
                               language: str,
                            #    function_name: Optional[str] = None,
                            #    class_name: Optional[str] = None,
                            #    start_line: Optional[int] = None,
                            #    end_line: Optional[int] = None) 
       ) -> CodeChunk:
        """
        Insert a code chunk with its embedding into the database.
        """
        async with self.get_session() as session:
            code_chunk = CodeChunk(
                session_id=session_id,
                file_path=file_path,
                code_content=code_content,
                embedding=embedding,
                language=language,
                # function_name=function_name,
                # class_name=class_name,
                # start_line=start_line,
                # end_line=end_line
            )

            session.add(code_chunk)
            await session.commit()
            await session.refresh(code_chunk)

            return code_chunk

    async def batch_insert_code_chunks(
        self,
        code_chunks_data: List[Dict[str, Any]]
    ) -> List[CodeChunk]:
        """
        Insert multiple code chunks in a single transaction.
        Much faster than individual inserts.
        """
        async with self.get_session() as session:
            code_chunks = []
            for data in code_chunks_data:
                code_chunk = CodeChunk(**data)
                code_chunks.append(code_chunk)

            session.add_all(code_chunks)
            await session.commit()
            # Refresh all objects to get their IDs
            for chunk in code_chunks:
                await session.refresh(chunk)
            return code_chunks


    async def similarity_search_code_chunk(self,
                               query_embedding: List[float],
                               session_id: uuid.UUID,
                               limit: int = 10,
                               language: Optional[str] = None,
                               similarity_threshold: Optional[float] = None) -> List[tuple]:
        """
        Search for similar code chunks using vector similarity.
        """
        async with self.get_session() as session:
            # Build query with similarity calculation
            distance_expr = CodeChunk.embedding.cosine_distance(query_embedding) 
            query = select(
                CodeChunk,
                distance_expr.label('distance')
            ).where(CodeChunk.session_id == session_id)
            
            # Apply language filter if specified
            if language:
                query = query.where(CodeChunk.language == language)

            # Apply similarity threshold if specified
            if similarity_threshold:
                distance_threshold = 1 - similarity_threshold
                query = query.where(distance_expr <= distance_threshold)

            # Order by similarity and limit results
            query = query.order_by('distance').limit(limit)

            result = await session.execute(query)
            rows = result.all()

            # Convert distance back to similarity score
            return [(chunk, 1 - distance) for chunk, distance in rows]

    async def semantic_search(self,
                             query_embedding: List[float],
                             search_type: str = 'cosine',
                             limit: int = 10):
        """
        Perform semantic search using different distance metrics.
        """
        async with self.get_session() as session:
            if search_type == 'cosine':
                distance_expr = CodeChunk.embedding.cosine_distance(query_embedding)
            elif search_type == 'l2':
                distance_expr = CodeChunk.embedding.l2_distance(query_embedding)
            elif search_type == 'inner_product':
                distance_expr = CodeChunk.embedding.max_inner_product(query_embedding)
            else:
                raise ValueError(f"Unsupported search type: {search_type}")

            query = select(
                CodeChunk,
                distance_expr.label('score')
            ).order_by('score').limit(limit)

            result = await session.execute(query)
            return result.all()

    # async def search_by_function_name(self,
    #                                  function_name: str,
    #                                  query_embedding: Optional[List[float]] = None,
    #                                  limit: int = 10) -> List[tuple]:
    #     """
    #     Search for code chunks by function name, optionally with semantic similarity.
    #     """
    #     async with self.get_session() as session:
    #         base_filter = CodeChunk.function_name.ilike(f'%{function_name}%')

    #         if query_embedding:
    #             distance_expr = CodeChunk.embedding.cosine_distance(query_embedding)
    #             query = select(
    #                 CodeChunk,
    #                 distance_expr.label('distance')
    #             ).where(base_filter).order_by('distance').limit(limit)
 
    #             result = await session.execute(query)
    #             rows = result.all()
    #             return [(chunk, 1 - distance) for chunk, distance in rows]
    #         else:
    #             query = select(CodeChunk).where(base_filter).limit(limit)
    #             result = await session.execute(query)
    #             chunks = result.scalars().all()
    #             return [(chunk, None) for chunk in chunks]

    async def get_chunk_by_id(self, chunk_id: uuid.UUID) -> Optional[CodeChunk]:
        """
        Retrieve a specific code chunk by ID.
        """
        async with self.get_session() as session:
            query = select(CodeChunk).where(CodeChunk.id == chunk_id)
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def update_chunk_embedding(self, chunk_id: uuid.UUID, new_embedding: List[float]) -> bool:
        """
        Update the embedding of a specific code chunk.
        """
        async with self.get_session() as session:
            query = select(CodeChunk).where(CodeChunk.id == chunk_id)
            result = await session.execute(query)
            chunk = result.scalar_one_or_none()

            if chunk:
                chunk.embedding = new_embedding
                chunk.updated_at = datetime.now()
                await session.commit()
                return True
            return False

    async def delete_chunk(self, chunk_id: uuid.UUID) -> bool:
        """
        Delete a code chunk by ID.
        """
        async with self.get_session() as session:
            query = select(CodeChunk).where(CodeChunk.id == chunk_id)
            result = await session.execute(query)
            chunk = result.scalar_one_or_none()

            if chunk:
                await session.delete(chunk)
                await session.commit()
                return True
            return False

    # async def get_statistics(self) -> Dict[str, Any]:
    #     """
    #     Get database statistics.
    #     """
    #     async with self.get_session() as session:
    #         # Count total chunks
    #         total_query = select(func.count(CodeChunk.id))
    #         total_result = await session.execute(total_query)
    #         total_chunks = total_result.scalar()

    #         # Get distinct languages
    #         lang_query = select(CodeChunk.language).distinct()
    #         lang_result = await session.execute(lang_query)
    #         languages = [row[0] for row in lang_result.all()]

    #         return {
    #             'total_chunks': total_chunks,
    #             'languages': languages,
    #             'languages_count': len(languages)
    #         }

    async def stream_all_chunks(
        self,
        batch_size: int = 100
    ) -> AsyncGenerator[List[CodeChunk], None]:
        """
        Stream all code chunks in batches for memory-efficient processing.
        """
        async with self.get_session() as session:
            offset = 0
            while True:
                query = select(CodeChunk).offset(offset).limit(batch_size)
                result = await session.execute(query)
                chunks = result.scalars().all()
                if not chunks:
                    break

                yield list(chunks)
                offset += batch_size

    async def bulk_similarity_search(
            self,
            query_embeddings: List[List[float]],
            session_id: uuid.UUID,
            limit: int = 10
        ) -> List[List[tuple]]:
        """
        Perform multiple similarity searches concurrently.
        """
        tasks = [
            self.similarity_search_code_chunk(embedding, session_id, limit=limit)
            for embedding in query_embeddings
        ]
        return await asyncio.gather(*tasks)

    async def close(self):
        """Close the database engine."""
        await self.engine.dispose()

# High-level async operations
class AsyncCodeSearchService:
    """
    High-level service for code search operations with concurrent processing.
    """

    def __init__(self, repository: RetrievalDatabaseConnector):
        self.repo = repository

    async def process_code_files_concurrently(self, 
                                            code_files: List[Dict[str, Any]], 
                                            embedding_function,
                                            max_concurrent: int = 10) -> List[CodeChunk]:
        """
        Process multiple code files concurrently with embedding generation.
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_single_file(file_data: Dict[str, Any]) -> CodeChunk:
            async with semaphore:
                # Generate embedding (assuming async embedding function)
                if asyncio.iscoroutinefunction(embedding_function):
                    embedding = await embedding_function(file_data['code_content'])
                else:
                    # Run sync embedding function in thread pool
                    embedding = await asyncio.get_event_loop().run_in_executor(
                        None, embedding_function, file_data['code_content']
                    )

                file_data['embedding'] = embedding
                return await self.repo.insert_code_chunk(**file_data)

        tasks = [process_single_file(file_data) for file_data in code_files]
        return await asyncio.gather(*tasks)

    async def hybrid_search(self,
                           query_embedding: List[float],
                           session_id: uuid.UUID,
                           limit: int = 10) -> List[tuple]:
        """
        Combine text search and semantic search for better results.
        """
        # Run both searches concurrently
        semantic_task = self.repo.similarity_search_code_chunk(query_embedding, session_id, limit=limit)

        semantic_results = await asyncio.gather(semantic_task)

        # Combine and deduplicate results
        combined_results = {}

        for chunk, score in semantic_results:
            combined_results[chunk.id] = (chunk, score, 'semantic')

        # for chunk, score in text_results:
        #     if chunk.id not in combined_results:
        #         combined_results[chunk.id] = (chunk, score, 'text')

        # Sort by score and return top results
        sorted_results = sorted(
            combined_results.values(), 
            key=lambda x: x[1] if x[1] is not None else 0, 
            reverse=True
        )

        return [(chunk, score) for chunk, score, _ in sorted_results[:limit]]

# Example usage
# async def async_example_usage():
#     """
#     Example of how to use the RetrievalDatabaseConnector.
#     """
#     # Initialize repository
#     DATABASE_URL = "postgresql://username:password@localhost/database"
#     repo = RetrievalDatabaseConnector(DATABASE_URL)

#     # Initialize database
#     await repo.initialize_database()

#     # Example: Insert a code chunk
#     sample_code = """
#     def calculate_similarity(vec1, vec2):
#         '''Calculate cosine similarity between two vectors.'''
#         import numpy as np
#         return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))
#     """
#     # Generate a dummy embedding (in real use, use OpenAI, Sentence Transformers, etc.)
#     dummy_embedding = np.random.rand(1536).tolist()

#     # Insert code chunk
#     chunk = await repo.insert_code_chunk(
#         session_id=uuid.uuid4(),
#         file_path="utils/similarity.py",
#         code_content=sample_code,
#         embedding=dummy_embedding,
#         language="python",
#         # function_name="calculate_similarity",
#         # start_line=10,
#         # end_line=15
#     )

#     print(f"Inserted chunk: {chunk.id}")

#     # Search for similar code
#     query_embedding = np.random.rand(1536).tolist()
#     results = await repo.similarity_search_code_chunk(
#         query_embedding=query_embedding,
#         session_id=chunk.session_id,
#         limit=5,
#         language="python"
#     )

#     print(f"Found {len(results)} similar chunks:")
#     for chunk, similarity in results:
#         print(f"  - {chunk.file_path} (similarity: {similarity:.3f})")

#     # Batch processing example
#     example_session_id = uuid.uuid4()
#     code_files = [
#         {
#             "session_id": example_session_id,
#             "file_path": f"example_{i}.py",
#             "code_content": f"def function_{i}(): pass",
#             "embedding": np.random.rand(1536).tolist(),
#             "language": "python",
#             # "function_name": f"function_{i}"
#         }
#         for i in range(100)
#     ]

#     # Batch insert
#     chunks = await repo.batch_insert_code_chunks(code_files)
#     print(f"Batch inserted {len(chunks)} chunks")

#     # Stream processing example
#     async for batch in repo.stream_all_chunks(batch_size=50):
#         print(f"Processing batch of {len(batch)} chunks")
#         # Process each batch
#         break  # Just show first batch

#     # High-level service usage
#     service = AsyncCodeSearchService(repo)

#     # Hybrid search
#     hybrid_results = await service.hybrid_search(
#         query_embedding=query_embedding,
#         session_id=example_session_id,
#         limit=10
#     )

#     print(f"Hybrid search found {len(hybrid_results)} results")

#     # Get statistics
#     # stats = await repo.get_statistics()
#     # print(f"Database stats: {stats}")

#     # Close repository
#     await repo.close()
