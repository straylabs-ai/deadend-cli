# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Generic embedding utilities for batch processing.

This module provides reusable functions for efficient batch embedding generation
using OpenAI's API, with fallback to parallel individual calls for robustness.
"""

import asyncio
from typing import List, TypeVar, Protocol
from openai import AsyncOpenAI

# Generic type for objects that can be embedded
T = TypeVar('T', bound='Embeddable')

class Embeddable(Protocol):
    """Protocol for objects that can be embedded.
    
    Objects implementing this protocol must have:
    - embeddings: List[float] | None attribute
    - A method to get embedding content as string
    """
    embeddings: List[float] | None
    
    def get_embedding_content(self) -> str:
        """Return the content to be embedded as a string."""
        ...

async def batch_embed_chunks(
    openai: AsyncOpenAI,
    embedding_model: str,
    embeddable_objects: List[T],
    batch_name: str = "chunks"
) -> List[T]:
    """Generate embeddings for a list of embeddable objects using batch API calls.
    
    This function optimizes embedding generation by:
    1. First attempting a single batch API call for all objects
    2. Falling back to parallel individual calls if batch fails
    
    Args:
        openai: AsyncOpenAI client instance
        embedding_model: Name of the embedding model to use
        embeddable_objects: List of objects implementing the Embeddable protocol
        batch_name: Name for logging purposes (e.g., "file chunks", "documents")
        
    Returns:
        List of successfully embedded objects (with embeddings populated)
    """
    if not embeddable_objects:
        return []
    # Prepare texts for batch embedding
    embedding_texts = [obj.get_embedding_content() for obj in embeddable_objects]

    try:
        response = await openai.embeddings.create(
            input=embedding_texts,
            model=embedding_model
        )
        for i, embedding_data in enumerate(response.data):
            if i < len(embeddable_objects):
                embeddable_objects[i].embeddings = embedding_data.embedding
        return embeddable_objects
    except Exception as e:
        print(f"Batch embedding failed for {batch_name}, falling back to individual calls: {e}")
        # Fallback to parallel individual calls
        return await _parallel_embed_fallback(
            openai=openai,
            embedding_model=embedding_model,
            embeddable_objects=embeddable_objects
        )

async def _parallel_embed_fallback(
    openai: AsyncOpenAI,
    embedding_model: str,
    embeddable_objects: List[T]
) -> List[T]:
    """Fallback method using parallel individual embedding calls.
    
    Args:
        openai: AsyncOpenAI client instance
        embedding_model: Name of the embedding model to use
        embeddable_objects: List of objects implementing the Embeddable protocol
        
    Returns:
        List of successfully embedded objects
    """
    # Create embedding tasks for all objects in parallel
    embedding_tasks = [
        _embed_single_object(obj, openai, embedding_model)
        for obj in embeddable_objects
    ]
    
    # Wait for all embeddings to complete
    await asyncio.gather(*embedding_tasks)
    
    # Filter out objects that failed to embed
    successful_objects = [
        obj for obj in embeddable_objects
        if obj.embeddings is not None
    ]
    
    return successful_objects

async def _embed_single_object(
    obj: T,
    openai: AsyncOpenAI,
    embedding_model: str
) -> None:
    """Embed a single object using OpenAI API.
    
    Args:
        obj: Object implementing the Embeddable protocol
        openai: AsyncOpenAI client instance
        embedding_model: Name of the embedding model to use
    """
    try:
        response = await openai.embeddings.create(
            input=obj.get_embedding_content(),
            model=embedding_model
        )
        assert len(response.data) == 1, (
            f'Expected 1 embedding, got {len(response.data)}'
        )
        obj.embeddings = response.data[0].embedding
    except Exception:
        obj.embeddings = None
