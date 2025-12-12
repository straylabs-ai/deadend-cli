# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Generic embedding utilities for batch processing.

This module provides reusable functions for efficient batch embedding generation
using OpenAI's API, with fallback to parallel individual calls for robustness.
"""

from typing import List, TypeVar, Protocol
import asyncio
from deadend_agent.models.registry import EmbedderClient

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
    embedder_client: EmbedderClient,
    embeddable_objects: List[T],
    batch_name: str = "chunks"
) -> List[T]:
    """Generate embeddings for a list of embeddable objects using batch API calls.
    
    This function optimizes embedding generation by:
    1. First attempting a single batch API call for all objects
    2. Falling back to parallel individual calls if batch fails
    
    Args:
        embedder_client: Embedding client instance
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
        # response = await openai.embeddings.create(
        #     input=embedding_texts,
        #     model=embedding_model
        # )

        response = await embedder_client.batch_embed(input=embedding_texts)
        for i, embedding_data in enumerate(response):
            if i < len(embeddable_objects):
                embeddable_objects[i].embeddings = embedding_data['embedding']
        return embeddable_objects
    except Exception as e:
        print(f"Batch embedding failed for {batch_name}, falling back to individual calls: {e}")
        # Fallback to individual embedding calls
        async def embed_single(obj: T) -> T:
            try:
                single_response = await embedder_client.batch_embed(input=[obj.get_embedding_content()])
                if single_response and len(single_response) > 0:
                    obj.embeddings = single_response[0]['embedding']
                return obj
            except Exception as single_e:
                print(f"Failed to embed individual chunk: {single_e}")
                return obj  # Return object with None embeddings
        
        # Process all objects in parallel
        results = await asyncio.gather(*[embed_single(obj) for obj in embeddable_objects])
        # Filter out objects that failed to embed (embeddings is None)
        return [obj for obj in results if obj.embeddings is not None]